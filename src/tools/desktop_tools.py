"""Desktop automation tools for the Laptop Assistant MCP server.

Provides tools for task scheduling, notifications, and window management.
"""

import asyncio
import json
import logging
import platform
import subprocess
from typing import Literal

from src.safety import create_confirmation_token

logger = logging.getLogger(__name__)


async def _run_powershell(command: str) -> tuple[int, str, str]:
    """Run a PowerShell command and return (returncode, stdout, stderr)."""
    # Use -EncodedCommand or just pass the command string?
    # For safety and complexity, passed as string to -Command is usually fine for internal use
    # provided we are careful with quoting.
    # Actually, simpler to use the same pattern as system_tools.
    
    process = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


def register_tools(mcp) -> None:
    """Register all desktop tools with the MCP server."""

    @mcp.tool()
    async def send_notification(title: str, message: str) -> str:
        """Send a desktop notification (toast/balloon tip).
        
        Args:
            title: The title of the notification.
            message: The body text of the notification.
        """
        if platform.system() != "Windows":
            return json.dumps({
                "status": "error",
                "message": "This tool is only supported on Windows.",
            })

        # PowerShell script to show a balloon tip
        # We escape single quotes in title and message to avoid breaking the command string
        safe_title = title.replace("'", "''")
        safe_message = message.replace("'", "''")
        
        ps_script = f"""
        [void] [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");
        $objNotifyIcon = New-Object System.Windows.Forms.NotifyIcon;
        $objNotifyIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon($PSHOME + "\\powershell.exe");
        $objNotifyIcon.BalloonTipIcon = "Info";
        $objNotifyIcon.BalloonTipTitle = '{safe_title}';
        $objNotifyIcon.BalloonTipText = '{safe_message}';
        $objNotifyIcon.Visible = $True;
        $objNotifyIcon.ShowBalloonTip(10000);
        Start-Sleep -Seconds 2; # Wait for tip to show before exiting (which kills the icon)
        """
        
        # We need to run this and NOT wait for it if we want it to be "fire and forget", 
        # but for the tool to return success, we should wait a bit.
        # Actually, if we exit too fast, the icon disappears. 
        # The script above has a sleep.
        
        code, stdout, stderr = await _run_powershell(ps_script)
        
        if code == 0:
            return json.dumps({
                "status": "success",
                "message": f"Notification '{title}' sent.",
            }, indent=2)
        else:
            return json.dumps({
                "status": "error",
                "message": f"Failed to send notification: {stderr or stdout}",
            }, indent=2)

    @mcp.tool()
    async def schedule_task(
        name: str, 
        command: str, 
        schedule_type: str = "DAILY", 
        start_time: str = "09:00"
    ) -> str:
        """Schedule a task to run automatically using Windows Task Scheduler.
        
        DESTRUCTIVE: This action requires confirmation.
        
        Args:
            name: Name of the task (must be unique).
            command: The command or script path to execute.
            schedule_type: When to run. Options: DAILY, WEEKLY, MONTHLY, ONCE, ONLOGON, ONSTART.
            start_time: Time to run in HH:mm format (24-hour). Default "09:00". 
                        Ignored for ONLOGON/ONSTART.
        """
        valid_types = ["DAILY", "WEEKLY", "MONTHLY", "ONCE", "ONLOGON", "ONSTART"]
        if schedule_type.upper() not in valid_types:
             return json.dumps({
                "status": "error",
                "message": f"Invalid schedule_type. Must be one of: {', '.join(valid_types)}",
            })

        async def _do_schedule():
            # Build schtasks command
            # /F forces creation (overwrites if exists)
            cmd_args = f'schtasks /create /tn "{name}" /tr "{command}" /sc {schedule_type} /f'
            
            if schedule_type.upper() not in ["ONLOGON", "ONSTART"]:
                cmd_args += f' /st {start_time}'
            
            code, stdout, stderr = await _run_powershell(cmd_args)
            
            if code == 0:
                return f"Successfully scheduled task '{name}'.\n{stdout}"
            else:
                return f"Failed to schedule task '{name}': {stderr or stdout}"

        return create_confirmation_token(
            action_name="schedule_task",
            description=f"Create scheduled task '{name}' to run '{command}' ({schedule_type} @ {start_time})",
            callback=_do_schedule,
        )

    @mcp.tool()
    async def list_scheduled_tasks(filter_str: str = "") -> str:
        """List scheduled tasks.
        
        Args:
            filter_str: Optional string to filter task names.
        """
        # CSV output for easier parsing
        code, stdout, stderr = await _run_powershell('schtasks /query /fo CSV /v')
        
        if code != 0:
             return json.dumps({
                "status": "error",
                "message": f"Failed to list tasks: {stderr}",
            })
            
        import csv
        import io
        
        tasks = []
        try:
            # Parse CSV output
            # stdout can be empty if no tasks found (unlikely)
            if stdout:
                f = io.StringIO(stdout)
                reader = csv.DictReader(f)
                for row in reader:
                    task_name = row.get("TaskName", "").strip('\\')
                    # Filter out standard Microsoft tasks to reduce noise if user didn't ask for them?
                    # The prompt implies automating *their* tasks.
                    # Let's simple filter by the argument first.
                    if filter_str and filter_str.lower() not in task_name.lower():
                        continue
                        
                    # Basic info
                    tasks.append({
                        "name": task_name,
                        "status": row.get("Status", "Unknown"),
                        "next_run_time": row.get("Next Run Time", ""),
                        "last_run_time": row.get("Last Run Time", ""),
                        "action": row.get("Task To Run", "")
                    })
        except Exception as e:
             return json.dumps({
                "status": "error",
                "message": f"Failed to parse task list: {e}",
                "raw_output": stdout[:500]
            })

        return json.dumps({
            "total_tasks": len(tasks),
            "tasks": tasks[:50], # Limit to 50 to avoid context overflow
            "note": "Showing max 50 tasks. Use filter_str to narrow down." if len(tasks) > 50 else ""
        }, indent=2)

    @mcp.tool()
    async def delete_scheduled_task(name: str) -> str:
        """Delete a scheduled task.
        
        DESTRUCTIVE: This action requires confirmation.
        
        Args:
            name: The name of the task to delete.
        """
        
        async def _do_delete():
            code, stdout, stderr = await _run_powershell(f'schtasks /delete /tn "{name}" /f')
            
            if code == 0:
                return f"Successfully deleted task '{name}'."
            else:
                return f"Failed to delete task '{name}': {stderr or stdout}"

        return create_confirmation_token(
            action_name="delete_scheduled_task",
            description=f"Delete scheduled task '{name}'",
            callback=_do_delete,
        )

    @mcp.tool()
    async def get_window_list() -> str:
        """Get a list of currently open application windows."""
        
        ps_script = 'Get-Process | Where-Object {$_.MainWindowTitle -ne ""} | Select-Object Id, MainWindowTitle, ProcessName | ConvertTo-Json'
        
        code, stdout, stderr = await _run_powershell(ps_script)
        
        if code != 0:
             return json.dumps({
                "status": "error",
                "message": f"Failed to get window list: {stderr}",
            })
            
        try:
            # PowerShell ConvertTo-Json might return a single object or list
            data = json.loads(stdout)
            if not isinstance(data, list):
                data = [data]
                
            windows = []
            for item in data:
                windows.append({
                    "pid": item.get("Id"),
                    "title": item.get("MainWindowTitle"),
                    "process_name": item.get("ProcessName")
                })
                
            return json.dumps({
                "count": len(windows),
                "windows": windows
            }, indent=2)
            
        except json.JSONDecodeError:
             return json.dumps({
                "status": "error",
                "message": "Failed to parse PowerShell output.",
                "raw": stdout
            })

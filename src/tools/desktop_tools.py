"""Desktop automation tools for the Laptop Assistant MCP server.

Provides tools for desktop notifications, Windows Task Scheduler management,
and window enumeration.

Adapted from PR #1 by abhishekpaliwal with improvements:
- Input validation against command injection
- Timeouts on all subprocess calls
- @timed decorator for performance logging
- Consistent error handling and JSON responses
"""

import asyncio
import csv
import io
import json
import logging
import platform
import re
from typing import Any

from src.perf import timed
from src.safety import create_confirmation_token

logger = logging.getLogger(__name__)

# Validation patterns
_SAFE_TASK_NAME = re.compile(r"^[\w\s\-./\\]+$")  # alphanumeric, spaces, -, ., /, \
_SAFE_TIME = re.compile(r"^\d{2}:\d{2}$")  # HH:mm format


async def _run_powershell(command: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a PowerShell command and return (returncode, stdout, stderr)."""
    try:
        process = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return (-1, "", f"Command timed out after {timeout} seconds")

        return (
            process.returncode,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )
    except Exception as e:
        return (-1, "", str(e))


def register_tools(mcp) -> None:
    """Register all desktop automation tools with the MCP server."""

    @mcp.tool()
    @timed
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

        # Escape single quotes for PowerShell string interpolation
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
        Start-Sleep -Seconds 2;
        """

        code, stdout, stderr = await _run_powershell(ps_script, timeout=15)

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
    @timed
    async def schedule_task(
        name: str,
        command: str,
        schedule_type: str = "DAILY",
        start_time: str = "09:00",
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
        # Input validation
        if not _SAFE_TASK_NAME.match(name):
            return json.dumps({
                "status": "error",
                "message": "Invalid task name. Only alphanumeric characters, spaces, hyphens, dots and path separators are allowed.",
            })

        if not _SAFE_TIME.match(start_time):
            return json.dumps({
                "status": "error",
                "message": "Invalid start_time format. Use HH:mm (e.g. '09:00').",
            })

        valid_types = {"DAILY", "WEEKLY", "MONTHLY", "ONCE", "ONLOGON", "ONSTART"}
        schedule_upper = schedule_type.upper()
        if schedule_upper not in valid_types:
            return json.dumps({
                "status": "error",
                "message": f"Invalid schedule_type. Must be one of: {', '.join(sorted(valid_types))}",
            })

        async def _do_schedule():
            # Use create_subprocess_exec with args list — safe from injection
            args = ["/create", "/tn", name, "/tr", command, "/sc", schedule_upper, "/f"]

            if schedule_upper not in {"ONLOGON", "ONSTART"}:
                args.extend(["/st", start_time])

            try:
                process = await asyncio.create_subprocess_exec(
                    "schtasks",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=60
                )

                if process.returncode == 0:
                    return f"Successfully scheduled task '{name}'.\n{stdout.decode().strip()}"
                else:
                    return f"Failed to schedule task '{name}': {stderr.decode().strip() or stdout.decode().strip()}"
            except asyncio.TimeoutError:
                return f"Task scheduling timed out for '{name}'."
            except Exception as e:
                return f"Failed to execute schtasks: {e}"

        return create_confirmation_token(
            action_name="schedule_task",
            description=f"Create scheduled task '{name}' to run '{command}' ({schedule_upper} @ {start_time})",
            callback=_do_schedule,
        )

    @mcp.tool()
    @timed
    async def list_scheduled_tasks(filter_str: str = "") -> str:
        """List scheduled tasks.

        Args:
            filter_str: Optional string to filter task names.
        """
        code, stdout, stderr = await _run_powershell(
            "schtasks /query /fo CSV /v", timeout=30
        )

        if code != 0:
            return json.dumps({
                "status": "error",
                "message": f"Failed to list tasks: {stderr}",
            })

        tasks: list[dict[str, Any]] = []
        try:
            if stdout:
                reader = csv.DictReader(io.StringIO(stdout))
                for row in reader:
                    task_name = row.get("TaskName", "").strip("\\")

                    if filter_str and filter_str.lower() not in task_name.lower():
                        continue

                    tasks.append({
                        "name": task_name,
                        "status": row.get("Status", "Unknown"),
                        "next_run_time": row.get("Next Run Time", ""),
                        "last_run_time": row.get("Last Run Time", ""),
                        "action": row.get("Task To Run", ""),
                    })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to parse task list: {e}",
                "raw_output": stdout[:500],
            })

        return json.dumps({
            "total_tasks": len(tasks),
            "tasks": tasks[:50],
            "note": "Showing max 50 tasks. Use filter_str to narrow down." if len(tasks) > 50 else "",
        }, indent=2)

    @mcp.tool()
    @timed
    async def delete_scheduled_task(name: str) -> str:
        """Delete a scheduled task.

        DESTRUCTIVE: This action requires confirmation.

        Args:
            name: The name of the task to delete.
        """
        # Input validation
        if not _SAFE_TASK_NAME.match(name):
            return json.dumps({
                "status": "error",
                "message": "Invalid task name. Only alphanumeric characters, spaces, hyphens, dots and path separators are allowed.",
            })

        async def _do_delete():
            try:
                process = await asyncio.create_subprocess_exec(
                    "schtasks",
                    "/delete",
                    "/tn",
                    name,
                    "/f",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30
                )

                if process.returncode == 0:
                    return f"Successfully deleted task '{name}'."
                else:
                    return f"Failed to delete task '{name}': {stderr.decode().strip() or stdout.decode().strip()}"
            except asyncio.TimeoutError:
                return f"Task deletion timed out for '{name}'."
            except Exception as e:
                return f"Failed to execute schtasks: {e}"

        return create_confirmation_token(
            action_name="delete_scheduled_task",
            description=f"Delete scheduled task '{name}'",
            callback=_do_delete,
        )

    @mcp.tool()
    @timed
    async def get_window_list() -> str:
        """Get a list of currently open application windows."""
        ps_script = (
            'Get-Process | Where-Object {$_.MainWindowTitle -ne ""} '
            '| Select-Object Id, MainWindowTitle, ProcessName | ConvertTo-Json'
        )

        code, stdout, stderr = await _run_powershell(ps_script, timeout=15)

        if code != 0:
            return json.dumps({
                "status": "error",
                "message": f"Failed to get window list: {stderr}",
            })

        try:
            data = json.loads(stdout)
            if not isinstance(data, list):
                data = [data]

            windows = [
                {
                    "pid": item.get("Id"),
                    "title": item.get("MainWindowTitle"),
                    "process_name": item.get("ProcessName"),
                }
                for item in data
            ]

            return json.dumps({
                "count": len(windows),
                "windows": windows,
            }, indent=2)

        except json.JSONDecodeError:
            return json.dumps({
                "status": "error",
                "message": "Failed to parse PowerShell output.",
                "raw": stdout[:500],
            })

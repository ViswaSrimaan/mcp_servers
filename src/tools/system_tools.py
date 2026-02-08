"""System tools for the Laptop Assistant MCP server.

Provides tools for system information, command execution, process management,
battery status, shutdown/restart, and network information.
"""

import asyncio
import json
import logging
import platform
from typing import Literal

import psutil

from src.safety import create_confirmation_token

logger = logging.getLogger(__name__)


def register_tools(mcp) -> None:
    """Register all system tools with the MCP server."""

    @mcp.tool()
    async def get_system_info() -> str:
        """Get comprehensive system information including CPU, memory, disk, and OS details."""
        info = {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "hostname": platform.node(),
                "architecture": platform.architecture()[0],
                "processor": platform.processor(),
            },
            "cpu": {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "usage_percent": psutil.cpu_percent(interval=1),
                "frequency_mhz": (
                    round(psutil.cpu_freq().current, 2) if psutil.cpu_freq() else None
                ),
            },
            "memory": {
                "total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "available_gb": round(
                    psutil.virtual_memory().available / (1024**3), 2
                ),
                "used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
                "usage_percent": psutil.virtual_memory().percent,
            },
            "disk": [],
        }

        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                info["disk"].append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "filesystem": partition.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "usage_percent": usage.percent,
                })
            except (PermissionError, OSError):
                continue

        return json.dumps(info, indent=2)

    @mcp.tool()
    async def run_command(command: str, timeout: int = 30) -> str:
        """Run a shell command on the system and return the output.

        POTENTIALLY DANGEROUS: This action requires confirmation to prevent
        command injection attacks. The tool will return a confirmation token
        that must be passed to confirm_action to execute.

        Uses PowerShell on Windows. The command runs asynchronously with a
        configurable timeout to prevent runaway processes.

        Args:
            command: The command to execute.
            timeout: Maximum execution time in seconds (default 30, max 300).
        """
        timeout = min(max(timeout, 1), 300)

        # Truncate command preview for display
        cmd_preview = command[:100] + "..." if len(command) > 100 else command

        async def _do_run_command():
            try:
                if platform.system() == "Windows":
                    process = await asyncio.create_subprocess_exec(
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                else:
                    process = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return json.dumps({
                    "status": "error",
                    "message": f"Command timed out after {timeout} seconds.",
                    "command": command,
                })
            except Exception as e:
                return json.dumps({
                    "status": "error",
                    "message": f"Failed to execute command: {e}",
                    "command": command,
                })

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            result = {
                "status": "success" if process.returncode == 0 else "error",
                "exit_code": process.returncode,
                "command": command,
            }

            if stdout_text:
                # Truncate if too long
                if len(stdout_text) > 10000:
                    stdout_text = stdout_text[:10000] + "\n... (output truncated)"
                result["stdout"] = stdout_text

            if stderr_text:
                if len(stderr_text) > 5000:
                    stderr_text = stderr_text[:5000] + "\n... (stderr truncated)"
                result["stderr"] = stderr_text

            return json.dumps(result, indent=2)

        return create_confirmation_token(
            action_name="run_command",
            description=f"Execute shell command: {cmd_preview}",
            callback=_do_run_command,
        )

    @mcp.tool()
    async def list_processes(
        sort_by: str = "memory",
        limit: int = 20,
    ) -> str:
        """List running processes with their resource usage.

        Args:
            sort_by: Sort criteria - 'memory', 'cpu', or 'name' (default: 'memory').
            limit: Maximum number of processes to return (default: 20, max: 100).
        """
        limit = min(max(limit, 1), 100)
        processes = []

        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                pinfo = proc.info
                processes.append({
                    "pid": pinfo["pid"],
                    "name": pinfo["name"],
                    "cpu_percent": round(pinfo["cpu_percent"] or 0, 1),
                    "memory_percent": round(pinfo["memory_percent"] or 0, 1),
                    "status": pinfo["status"],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        sort_key = {
            "memory": lambda p: p["memory_percent"],
            "cpu": lambda p: p["cpu_percent"],
            "name": lambda p: p["name"].lower(),
        }.get(sort_by, lambda p: p["memory_percent"])

        processes.sort(key=sort_key, reverse=(sort_by != "name"))

        return json.dumps({
            "total_processes": len(processes),
            "showing": min(limit, len(processes)),
            "sort_by": sort_by,
            "processes": processes[:limit],
        }, indent=2)

    @mcp.tool()
    async def kill_process(pid: int, process_name: str = "") -> str:
        """Kill/terminate a running process by PID.

        DESTRUCTIVE: This action requires confirmation. The tool will return a
        confirmation token that must be passed to confirm_action to execute.

        Args:
            pid: The process ID to terminate.
            process_name: Optional process name for display in the confirmation message.
        """
        # Validate the process exists first
        try:
            proc = psutil.Process(pid)
            actual_name = proc.name()
            display_name = process_name or actual_name
        except psutil.NoSuchProcess:
            return json.dumps({
                "status": "error",
                "message": f"No process found with PID {pid}.",
            })
        except psutil.AccessDenied:
            return json.dumps({
                "status": "error",
                "message": f"Access denied to process PID {pid}.",
            })

        async def _do_kill():
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                # Wait up to 5 seconds for graceful termination
                try:
                    proc.wait(timeout=5)
                except psutil.TimeoutExpired:
                    proc.kill()  # Force kill if terminate didn't work
                return f"Process '{display_name}' (PID {pid}) has been terminated."
            except psutil.NoSuchProcess:
                return f"Process PID {pid} no longer exists (may have already exited)."
            except psutil.AccessDenied:
                return f"Access denied: cannot terminate PID {pid}. May require elevated privileges."
            except Exception as e:
                return f"Failed to kill process: {e}"

        return create_confirmation_token(
            action_name="kill_process",
            description=f"Terminate process '{display_name}' (PID: {pid})",
            callback=_do_kill,
        )

    @mcp.tool()
    async def get_battery_status() -> str:
        """Get battery status including charge level, plugged-in state, and time remaining."""
        battery = psutil.sensors_battery()

        if battery is None:
            return json.dumps({
                "status": "info",
                "message": "No battery detected (desktop computer or battery not accessible).",
            })

        time_left = battery.secsleft
        if time_left == psutil.POWER_TIME_UNLIMITED:
            time_remaining = "Charging / Unlimited"
        elif time_left == psutil.POWER_TIME_UNKNOWN:
            time_remaining = "Unknown"
        else:
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            time_remaining = f"{hours}h {minutes}m"

        return json.dumps({
            "percent": round(battery.percent, 1),
            "plugged_in": battery.power_plugged,
            "time_remaining": time_remaining,
        }, indent=2)

    @mcp.tool()
    async def shutdown_restart(action: str) -> str:
        """Shutdown, restart, or put the computer to sleep.

        DESTRUCTIVE: This action requires confirmation. The tool will return a
        confirmation token that must be passed to confirm_action to execute.

        The action is scheduled with a 60-second delay so it can be aborted
        with 'shutdown /a' on Windows if needed.

        Args:
            action: The action to perform - 'shutdown', 'restart', or 'sleep'.
        """
        valid_actions = {"shutdown", "restart", "sleep"}
        if action not in valid_actions:
            return json.dumps({
                "status": "error",
                "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
            })

        async def _do_action():
            try:
                if platform.system() == "Windows":
                    if action == "shutdown":
                        cmd = ["shutdown", "/s", "/t", "60"]
                    elif action == "restart":
                        cmd = ["shutdown", "/r", "/t", "60"]
                    else:  # sleep
                        cmd = [
                            "rundll32.exe",
                            "powrprof.dll,SetSuspendState",
                            "0,1,0",
                        ]
                else:
                    if action == "shutdown":
                        cmd = ["shutdown", "-h", "+1"]
                    elif action == "restart":
                        cmd = ["shutdown", "-r", "+1"]
                    else:
                        cmd = ["systemctl", "suspend"]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await process.communicate()

                if process.returncode == 0:
                    if action in ("shutdown", "restart"):
                        return (
                            f"System {action} scheduled in 60 seconds. "
                            f"To abort on Windows, run: shutdown /a"
                        )
                    return "System is entering sleep mode."
                else:
                    error = stderr.decode("utf-8", errors="replace").strip()
                    return f"Failed to {action}: {error}"
            except Exception as e:
                return f"Failed to {action}: {e}"

        return create_confirmation_token(
            action_name="shutdown_restart",
            description=f"{action.capitalize()} this computer (60-second delay for shutdown/restart)",
            callback=_do_action,
        )

    @mcp.tool()
    async def get_network_info() -> str:
        """Get network interface information including IP addresses and traffic statistics."""
        interfaces = []

        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io_counters = psutil.net_io_counters(pernic=True)

        for iface_name, iface_addrs in addrs.items():
            iface_info = {
                "name": iface_name,
                "addresses": [],
                "is_up": stats.get(iface_name, None) is not None
                and stats[iface_name].isup,
            }

            for addr in iface_addrs:
                addr_info = {
                    "family": str(addr.family.name),
                    "address": addr.address,
                }
                if addr.netmask:
                    addr_info["netmask"] = addr.netmask
                iface_info["addresses"].append(addr_info)

            if iface_name in io_counters:
                io = io_counters[iface_name]
                iface_info["traffic"] = {
                    "bytes_sent_mb": round(io.bytes_sent / (1024**2), 2),
                    "bytes_recv_mb": round(io.bytes_recv / (1024**2), 2),
                    "packets_sent": io.packets_sent,
                    "packets_recv": io.packets_recv,
                }

            interfaces.append(iface_info)

        return json.dumps({"interfaces": interfaces}, indent=2)

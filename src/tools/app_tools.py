"""Application management tools for the Laptop Assistant MCP server.

Provides tools for listing, searching, installing, uninstalling, and updating
applications using Windows Package Manager (winget).
"""

import asyncio
import json
import logging

from src.safety import create_confirmation_token

logger = logging.getLogger(__name__)


async def _run_winget(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a winget command and return (returncode, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        "winget",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        return -1, "", f"Command timed out after {timeout} seconds."

    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


def register_tools(mcp) -> None:
    """Register all app management tools with the MCP server."""

    @mcp.tool()
    async def list_installed_apps(filter_name: str = "") -> str:
        """List installed applications using winget.

        Args:
            filter_name: Optional filter to search installed apps by name (default: '' for all).
        """
        args = ["list", "--accept-source-agreements"]
        if filter_name:
            args.extend(["--name", filter_name])

        returncode, stdout, stderr = await _run_winget(args)

        if returncode != 0 and not stdout:
            return json.dumps({
                "status": "error",
                "message": f"Failed to list apps: {stderr or 'Unknown error'}",
            })

        return json.dumps({
            "status": "success",
            "filter": filter_name or "(none)",
            "output": stdout,
        }, indent=2)

    @mcp.tool()
    async def search_available_apps(query: str) -> str:
        """Search for available applications in the winget repository.

        Args:
            query: Search query for finding applications.
        """
        args = ["search", query, "--accept-source-agreements"]

        returncode, stdout, stderr = await _run_winget(args)

        if returncode != 0 and not stdout:
            return json.dumps({
                "status": "error",
                "message": f"Search failed: {stderr or 'No results found'}",
            })

        return json.dumps({
            "status": "success",
            "query": query,
            "output": stdout,
        }, indent=2)

    @mcp.tool()
    async def install_app(app_id: str, source: str = "winget") -> str:
        """Install an application using winget.

        Args:
            app_id: The winget package ID to install (e.g., 'Google.Chrome', 'Mozilla.Firefox').
            source: The package source (default: 'winget').
        """
        args = [
            "install",
            "--id",
            app_id,
            "--source",
            source,
            "--silent",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]

        returncode, stdout, stderr = await _run_winget(args, timeout=300)

        if returncode == 0:
            return json.dumps({
                "status": "success",
                "message": f"Successfully installed '{app_id}'.",
                "output": stdout,
            }, indent=2)
        else:
            return json.dumps({
                "status": "error",
                "message": f"Failed to install '{app_id}'.",
                "output": stdout,
                "error": stderr,
            }, indent=2)

    @mcp.tool()
    async def uninstall_app(app_id: str) -> str:
        """Uninstall an application using winget.

        DESTRUCTIVE: This action requires confirmation. The tool will return a
        confirmation token that must be passed to confirm_action to execute.

        Args:
            app_id: The winget package ID to uninstall.
        """

        async def _do_uninstall():
            args = [
                "uninstall",
                "--id",
                app_id,
                "--silent",
                "--accept-source-agreements",
            ]
            returncode, stdout, stderr = await _run_winget(args, timeout=300)

            if returncode == 0:
                return f"Successfully uninstalled '{app_id}'.\n{stdout}"
            else:
                return f"Failed to uninstall '{app_id}': {stderr or stdout}"

        return create_confirmation_token(
            action_name="uninstall_app",
            description=f"Uninstall application '{app_id}' from this computer",
            callback=_do_uninstall,
        )

    @mcp.tool()
    async def update_app(app_id: str) -> str:
        """Update an installed application using winget.

        DESTRUCTIVE: This action requires confirmation because it modifies
        installed software.

        Args:
            app_id: The winget package ID to update.
        """

        async def _do_update():
            args = [
                "upgrade",
                "--id",
                app_id,
                "--silent",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
            returncode, stdout, stderr = await _run_winget(args, timeout=300)

            if returncode == 0:
                return f"Successfully updated '{app_id}'.\n{stdout}"
            else:
                return f"Failed to update '{app_id}': {stderr or stdout}"

        return create_confirmation_token(
            action_name="update_app",
            description=f"Update application '{app_id}' to the latest version",
            callback=_do_update,
        )

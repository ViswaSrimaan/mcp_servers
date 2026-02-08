"""Utility tools for the Laptop Assistant MCP server.

Provides tools for clipboard management, opening applications, and screenshots.
"""

import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from src.security_config import is_execution_safe, is_path_allowed

logger = logging.getLogger(__name__)


def register_tools(mcp) -> None:
    """Register all utility tools with the MCP server."""

    @mcp.tool()
    async def get_clipboard() -> str:
        """Get the current text content from the system clipboard."""
        try:
            import pyperclip

            content = pyperclip.paste()

            if not content:
                return json.dumps({
                    "status": "info",
                    "message": "Clipboard is empty or contains non-text content.",
                })

            # Truncate if very long
            truncated = len(content) > 5000
            if truncated:
                content = content[:5000]

            return json.dumps({
                "status": "success",
                "content": content,
                "truncated": truncated,
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to read clipboard: {e}",
            })

    @mcp.tool()
    async def set_clipboard(text: str) -> str:
        """Set text content to the system clipboard.

        Args:
            text: The text to copy to the clipboard.
        """
        try:
            import pyperclip

            pyperclip.copy(text)
            preview = text[:100] + "..." if len(text) > 100 else text
            return json.dumps({
                "status": "success",
                "message": "Text copied to clipboard.",
                "preview": preview,
                "length": len(text),
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to set clipboard: {e}",
            })

    @mcp.tool()
    async def open_application(app_name_or_path: str) -> str:
        """Open an application by name or file path.

        On Windows, this uses os.startfile which works with:
        - Safe application names (e.g., 'notepad', 'calc')
        - Safe file types (documents, images, media)
        - URLs (opens in default browser)

        Args:
            app_name_or_path: Application name, file path, or URL to open.
        """
        # Security: Validate the target is safe to execute
        safe, reason = is_execution_safe(app_name_or_path)
        if not safe:
            return json.dumps({
                "status": "error",
                "message": reason,
            })

        try:
            if platform.system() == "Windows":
                os.startfile(app_name_or_path)
            else:
                import asyncio
                import subprocess

                def _open_app():
                    if platform.system() == "Darwin":
                        subprocess.Popen(["open", app_name_or_path])
                    else:
                        subprocess.Popen(["xdg-open", app_name_or_path])

                await asyncio.to_thread(_open_app)

            return json.dumps({
                "status": "success",
                "message": f"Opened '{app_name_or_path}'.",
            }, indent=2)
        except FileNotFoundError:
            return json.dumps({
                "status": "error",
                "message": f"Application or file not found: '{app_name_or_path}'.",
            })
        except OSError as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to open '{app_name_or_path}': {e}",
            })

    @mcp.tool()
    async def take_screenshot(save_path: str = "") -> str:
        """Take a screenshot of the current screen and save it to a file.

        Args:
            save_path: Path to save the screenshot. If empty, saves to a temp directory.
        """
        try:
            from PIL import ImageGrab

            if not save_path:
                save_path = str(
                    Path(tempfile.gettempdir()) / "laptop_assistant_screenshot.png"
                )

            target = Path(save_path).resolve()

            # Security: Validate save path (but allow temp directory)
            if not str(target).startswith(tempfile.gettempdir()):
                allowed, reason = is_path_allowed(target, for_write=True)
                if not allowed:
                    return json.dumps({
                        "status": "error",
                        "message": reason,
                    })

            target.parent.mkdir(parents=True, exist_ok=True)

            img = ImageGrab.grab()
            img.save(str(target), "PNG")

            return json.dumps({
                "status": "success",
                "message": "Screenshot captured.",
                "path": str(target),
                "resolution": f"{img.size[0]}x{img.size[1]}",
            }, indent=2)
        except ImportError:
            return json.dumps({
                "status": "error",
                "message": "Screenshot requires the Pillow library with ImageGrab support (Windows only).",
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to take screenshot: {e}",
            })

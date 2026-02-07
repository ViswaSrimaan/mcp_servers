"""File management tools for the Laptop Assistant MCP server.

Provides tools for listing, reading, writing, copying, moving, deleting,
and searching files and directories.
"""

import json
import logging
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

from src.safety import create_confirmation_token

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def _format_timestamp(timestamp: float) -> str:
    """Format a Unix timestamp to an ISO format string."""
    return datetime.fromtimestamp(timestamp).isoformat()


def register_tools(mcp) -> None:
    """Register all file tools with the MCP server."""

    @mcp.tool()
    async def list_files(path: str, show_hidden: bool = False) -> str:
        """List files and directories at the specified path.

        Args:
            path: The directory path to list contents of.
            show_hidden: Whether to include hidden files (default: False).
        """
        target = Path(path).resolve()

        if not target.exists():
            return json.dumps({"status": "error", "message": f"Path does not exist: {target}"})

        if not target.is_dir():
            return json.dumps({"status": "error", "message": f"Path is not a directory: {target}"})

        entries = []
        try:
            for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                name = entry.name

                if not show_hidden and name.startswith("."):
                    continue

                try:
                    st = entry.stat()
                    entries.append({
                        "name": name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": _format_size(st.st_size) if entry.is_file() else None,
                        "size_bytes": st.st_size if entry.is_file() else None,
                        "modified": _format_timestamp(st.st_mtime),
                    })
                except (PermissionError, OSError):
                    entries.append({
                        "name": name,
                        "type": "unknown",
                        "error": "Permission denied",
                    })
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})

        return json.dumps({
            "path": str(target),
            "total_entries": len(entries),
            "entries": entries,
        }, indent=2)

    @mcp.tool()
    async def read_file(path: str, max_lines: int = 500) -> str:
        """Read the contents of a text file.

        For binary files, returns file metadata instead of content.

        Args:
            path: The file path to read.
            max_lines: Maximum number of lines to read (default: 500, max: 5000).
        """
        max_lines = min(max(max_lines, 1), 5000)
        target = Path(path).resolve()

        if not target.exists():
            return json.dumps({"status": "error", "message": f"File does not exist: {target}"})

        if not target.is_file():
            return json.dumps({"status": "error", "message": f"Path is not a file: {target}"})

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file - return metadata instead
            st = target.stat()
            return json.dumps({
                "status": "info",
                "message": "Binary file detected, cannot display content.",
                "path": str(target),
                "size": _format_size(st.st_size),
                "extension": target.suffix,
            })
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})

        lines = content.splitlines()
        total_lines = len(lines)
        truncated = total_lines > max_lines

        if truncated:
            lines = lines[:max_lines]

        return json.dumps({
            "path": str(target),
            "total_lines": total_lines,
            "showing_lines": len(lines),
            "truncated": truncated,
            "content": "\n".join(lines),
        }, indent=2)

    @mcp.tool()
    async def write_file(path: str, content: str, append: bool = False) -> str:
        """Write content to a file. Creates the file and parent directories if they don't exist.

        Args:
            path: The file path to write to.
            content: The text content to write.
            append: If True, append to existing file. If False, overwrite (default: False).
        """
        target = Path(path).resolve()

        try:
            target.parent.mkdir(parents=True, exist_ok=True)

            if append:
                with open(target, "a", encoding="utf-8") as f:
                    f.write(content)
                action = "appended to"
            else:
                target.write_text(content, encoding="utf-8")
                action = "written to"

            st = target.stat()
            return json.dumps({
                "status": "success",
                "message": f"Content {action} file.",
                "path": str(target),
                "size": _format_size(st.st_size),
            })
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Failed to write file: {e}"})

    @mcp.tool()
    async def create_directory(path: str) -> str:
        """Create a directory and any necessary parent directories.

        Args:
            path: The directory path to create.
        """
        target = Path(path).resolve()

        try:
            target.mkdir(parents=True, exist_ok=True)
            return json.dumps({
                "status": "success",
                "message": f"Directory created (or already exists).",
                "path": str(target),
            })
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Failed to create directory: {e}"})

    @mcp.tool()
    async def delete_file(path: str) -> str:
        """Delete a file or directory.

        DESTRUCTIVE: This action requires confirmation. The tool will return a
        confirmation token that must be passed to confirm_action to execute.

        For directories, this performs a recursive delete.

        Args:
            path: The file or directory path to delete.
        """
        target = Path(path).resolve()

        if not target.exists():
            return json.dumps({"status": "error", "message": f"Path does not exist: {target}"})

        is_dir = target.is_dir()
        if is_dir:
            # Count contents for the warning
            try:
                item_count = sum(1 for _ in target.rglob("*"))
            except PermissionError:
                item_count = "unknown (permission denied)"
            description = f"Delete directory '{target}' and all its contents ({item_count} items)"
        else:
            size = _format_size(target.stat().st_size)
            description = f"Delete file '{target}' ({size})"

        async def _do_delete():
            try:
                if is_dir:
                    shutil.rmtree(target)
                else:
                    target.unlink()
                return f"Successfully deleted: {target}"
            except PermissionError:
                return f"Permission denied: {target}"
            except Exception as e:
                return f"Failed to delete: {e}"

        return create_confirmation_token(
            action_name="delete_file",
            description=description,
            callback=_do_delete,
        )

    @mcp.tool()
    async def move_file(source: str, destination: str) -> str:
        """Move or rename a file or directory.

        DESTRUCTIVE: This action requires confirmation because it can overwrite
        existing files at the destination.

        Args:
            source: The source file or directory path.
            destination: The destination path.
        """
        src = Path(source).resolve()
        dst = Path(destination).resolve()

        if not src.exists():
            return json.dumps({"status": "error", "message": f"Source does not exist: {src}"})

        overwrites = dst.exists()
        description = f"Move '{src}' to '{dst}'"
        if overwrites:
            description += " (WARNING: destination exists and will be overwritten)"

        async def _do_move():
            try:
                shutil.move(str(src), str(dst))
                return f"Successfully moved '{src}' to '{dst}'"
            except PermissionError:
                return f"Permission denied moving '{src}' to '{dst}'"
            except Exception as e:
                return f"Failed to move: {e}"

        return create_confirmation_token(
            action_name="move_file",
            description=description,
            callback=_do_move,
        )

    @mcp.tool()
    async def copy_file(source: str, destination: str) -> str:
        """Copy a file or directory to a new location.

        For directories, performs a recursive copy.

        Args:
            source: The source file or directory path.
            destination: The destination path.
        """
        src = Path(source).resolve()
        dst = Path(destination).resolve()

        if not src.exists():
            return json.dumps({"status": "error", "message": f"Source does not exist: {src}"})

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)

            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dst))

            return json.dumps({
                "status": "success",
                "message": f"Copied '{src}' to '{dst}'",
                "source": str(src),
                "destination": str(dst),
            })
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied."})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Failed to copy: {e}"})

    @mcp.tool()
    async def search_files(path: str, pattern: str, recursive: bool = True) -> str:
        """Search for files matching a glob pattern.

        Args:
            path: The directory to search in.
            pattern: Glob pattern to match (e.g., '*.txt', '**/*.py', 'report*').
            recursive: Whether to search subdirectories (default: True).
        """
        target = Path(path).resolve()

        if not target.exists() or not target.is_dir():
            return json.dumps({"status": "error", "message": f"Directory does not exist: {target}"})

        try:
            if recursive:
                matches = list(target.rglob(pattern))
            else:
                matches = list(target.glob(pattern))

            results = []
            for match in matches[:200]:  # Limit results
                try:
                    st = match.stat()
                    results.append({
                        "path": str(match),
                        "type": "directory" if match.is_dir() else "file",
                        "size": _format_size(st.st_size) if match.is_file() else None,
                        "modified": _format_timestamp(st.st_mtime),
                    })
                except (PermissionError, OSError):
                    results.append({"path": str(match), "error": "Access denied"})

            return json.dumps({
                "search_path": str(target),
                "pattern": pattern,
                "recursive": recursive,
                "total_matches": len(matches),
                "showing": len(results),
                "results": results,
            }, indent=2)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Search failed: {e}"})

    @mcp.tool()
    async def get_file_info(path: str) -> str:
        """Get detailed information about a file or directory.

        Args:
            path: The file or directory path.
        """
        target = Path(path).resolve()

        if not target.exists():
            return json.dumps({"status": "error", "message": f"Path does not exist: {target}"})

        try:
            st = target.stat()

            info = {
                "path": str(target),
                "name": target.name,
                "type": "directory" if target.is_dir() else "file",
                "size": _format_size(st.st_size),
                "size_bytes": st.st_size,
                "created": _format_timestamp(st.st_ctime),
                "modified": _format_timestamp(st.st_mtime),
                "accessed": _format_timestamp(st.st_atime),
                "extension": target.suffix if target.is_file() else None,
                "is_hidden": target.name.startswith("."),
                "is_symlink": target.is_symlink(),
                "readable": os.access(target, os.R_OK),
                "writable": os.access(target, os.W_OK),
            }

            if target.is_dir():
                try:
                    contents = list(target.iterdir())
                    info["num_files"] = sum(1 for c in contents if c.is_file())
                    info["num_dirs"] = sum(1 for c in contents if c.is_dir())
                except PermissionError:
                    info["contents"] = "Permission denied"

            return json.dumps(info, indent=2)
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Failed to get info: {e}"})

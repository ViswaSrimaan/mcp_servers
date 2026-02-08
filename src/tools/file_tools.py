"""File management tools for the Laptop Assistant MCP server.

Provides tools for listing, reading, writing, copying, moving, deleting,
and searching files and directories.
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from src.safety import create_confirmation_token
from src.security_config import is_path_allowed

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


def _collect_directory_entries(target: Path, show_hidden: bool) -> list[dict[str, Any]]:
    """Collect directory entries with their metadata.
    
    Helper function to reduce cognitive complexity.
    """
    entries = []
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if not show_hidden and entry.name.startswith("."):
            continue
        entries.append(_get_entry_info(entry))
    return entries


def _get_entry_info(entry: Path) -> dict[str, Any]:
    """Get info for a single directory entry."""
    try:
        st = entry.stat()
        return {
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "size": _format_size(st.st_size) if entry.is_file() else None,
            "size_bytes": st.st_size if entry.is_file() else None,
            "modified": _format_timestamp(st.st_mtime),
        }
    except (PermissionError, OSError):
        return {
            "name": entry.name,
            "type": "unknown",
            "error": "Permission denied",
        }


def _read_text_file(target: Path, max_lines: int) -> dict[str, Any]:
    """Read a text file and return formatted content.
    
    Helper function to reduce cognitive complexity.
    """
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        st = target.stat()
        return {
            "status": "info",
            "message": "Binary file detected, cannot display content.",
            "path": str(target),
            "size": _format_size(st.st_size),
            "extension": target.suffix,
        }
    except PermissionError:
        return {"status": "error", "message": f"Permission denied: {target}"}

    lines = content.splitlines()
    total_lines = len(lines)
    truncated = total_lines > max_lines
    if truncated:
        lines = lines[:max_lines]

    return {
        "path": str(target),
        "total_lines": total_lines,
        "showing_lines": len(lines),
        "truncated": truncated,
        "content": "\n".join(lines),
    }


def _collect_search_results(matches: list[Path], limit: int = 200) -> list[dict[str, Any]]:
    """Collect search results with metadata.
    
    Helper function to reduce cognitive complexity.
    """
    results = []
    for match in matches[:limit]:
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
    return results


def _get_detailed_file_info(target: Path) -> dict[str, Any]:
    """Get detailed information about a file or directory.
    
    Helper function to reduce cognitive complexity.
    """
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
    }

    if target.is_dir():
        info.update(_get_directory_stats(target))

    return info


def _get_directory_stats(target: Path) -> dict[str, Any]:
    """Get stats for a directory (file/folder counts)."""
    try:
        contents = list(target.iterdir())
        return {
            "num_files": sum(1 for c in contents if c.is_file()),
            "num_dirs": sum(1 for c in contents if c.is_dir()),
        }
    except PermissionError:
        return {"contents": "Permission denied"}


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

        allowed, reason = is_path_allowed(target)
        if not allowed:
            return json.dumps({"status": "error", "message": reason})

        if not target.exists():
            return json.dumps({"status": "error", "message": f"Path does not exist: {target}"})

        if not target.is_dir():
            return json.dumps({"status": "error", "message": f"Path is not a directory: {target}"})

        try:
            entries = await asyncio.to_thread(_collect_directory_entries, target, show_hidden)
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

        allowed, reason = is_path_allowed(target)
        if not allowed:
            return json.dumps({"status": "error", "message": reason})

        if not target.exists():
            return json.dumps({"status": "error", "message": f"File does not exist: {target}"})

        if not target.is_file():
            return json.dumps({"status": "error", "message": f"Path is not a file: {target}"})

        result = await asyncio.to_thread(_read_text_file, target, max_lines)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def write_file(path: str, content: str, append: bool = False) -> str:
        """Write content to a file. Creates the file and parent directories if they don't exist.

        Args:
            path: The file path to write to.
            content: The text content to write.
            append: If True, append to existing file. If False, overwrite (default: False).
        """
        target = Path(path).resolve()

        allowed, reason = is_path_allowed(target, for_write=True)
        if not allowed:
            return json.dumps({"status": "error", "message": reason})

        def _write_sync():
            target.parent.mkdir(parents=True, exist_ok=True)
            if append:
                with open(target, "a", encoding="utf-8") as f:
                    f.write(content)
                return "appended to"
            else:
                target.write_text(content, encoding="utf-8")
                return "written to"

        try:
            action = await asyncio.to_thread(_write_sync)
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
            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
            return json.dumps({
                "status": "success",
                "message": "Directory created (or already exists).",
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
            try:
                item_count = sum(1 for _ in target.rglob("*"))
            except PermissionError:
                item_count = "unknown (permission denied)"
            description = f"Delete directory '{target}' and all its contents ({item_count} items)"
        else:
            size = _format_size(target.stat().st_size)
            description = f"Delete file '{target}' ({size})"

        async def _do_delete():
            def _delete_sync():
                if is_dir:
                    shutil.rmtree(target)
                else:
                    target.unlink()
                return f"Successfully deleted: {target}"

            try:
                return await asyncio.to_thread(_delete_sync)
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
                await asyncio.to_thread(shutil.move, str(src), str(dst))
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

        def _copy_sync():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dst))

        try:
            await asyncio.to_thread(_copy_sync)
            return json.dumps({
                "status": "success",
                "message": f"Copied '{src}' to '{dst}'",
                "source": str(src),
                "destination": str(dst),
            })
        except PermissionError:
            return json.dumps({"status": "error", "message": "Permission denied."})
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

        def _search_sync():
            if recursive:
                return list(target.rglob(pattern))
            return list(target.glob(pattern))

        try:
            matches = await asyncio.to_thread(_search_sync)
            results = _collect_search_results(matches)

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
            info = await asyncio.to_thread(_get_detailed_file_info, target)
            return json.dumps(info, indent=2)
        except PermissionError:
            return json.dumps({"status": "error", "message": f"Permission denied: {target}"})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Failed to get info: {e}"})

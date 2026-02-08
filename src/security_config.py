"""Security configuration and validation utilities for the MCP server.

This module provides security hardening to prevent:
- Path traversal attacks
- SSRF (Server-Side Request Forgery)
- Unrestricted file execution
"""

import ipaddress
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# =============================================================================
# PATH SECURITY CONFIGURATION
# =============================================================================

# Directories where file operations are allowed.
# If empty, all paths are allowed (less secure, but maintains original behavior).
# Users can customize this list via environment variable.
ALLOWED_DIRECTORIES: list[str] = []

# Parse from environment variable (comma-separated paths)
_env_allowed = os.environ.get("MCP_ALLOWED_DIRECTORIES", "")
if _env_allowed:
    ALLOWED_DIRECTORIES = [p.strip() for p in _env_allowed.split(",") if p.strip()]

# Directories that are ALWAYS blocked (even if ALLOWED_DIRECTORIES is empty)
BLOCKED_DIRECTORIES: list[str] = [
    # Windows system directories
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
    # Linux/Unix system directories
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/boot",
    "/lib",
    "/lib64",
    "/var",
    "/root",
]

# File extensions that cannot be written (executable code)
BLOCKED_WRITE_EXTENSIONS: set[str] = {
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msc", ".scr", ".pif", ".com", ".hta",
    ".dll", ".sys", ".drv",
    ".sh", ".bash", ".zsh", ".fish",  # Unix shells
}


def is_path_allowed(path: str | Path, for_write: bool = False) -> tuple[bool, str]:
    """Check if a file path is allowed for operations.
    
    Args:
        path: The file path to validate.
        for_write: If True, also checks blocked write extensions.
    
    Returns:
        Tuple of (is_allowed, reason_if_blocked).
    """
    try:
        resolved = Path(path).resolve()
        resolved_str = str(resolved)
    except (ValueError, OSError) as e:
        return False, f"Invalid path: {e}"

    # Check blocked directories (always enforced)
    for blocked in BLOCKED_DIRECTORIES:
        blocked_resolved = str(Path(blocked).resolve())
        if resolved_str.lower().startswith(blocked_resolved.lower()):
            return False, f"Access to system directory '{blocked}' is not allowed"

    # Check allowed directories (if configured)
    if ALLOWED_DIRECTORIES:
        in_allowed = False
        for allowed in ALLOWED_DIRECTORIES:
            allowed_resolved = str(Path(allowed).resolve())
            if resolved_str.lower().startswith(allowed_resolved.lower()):
                in_allowed = True
                break
        if not in_allowed:
            return False, (
                f"Path '{resolved}' is outside allowed directories. "
                f"Allowed: {', '.join(ALLOWED_DIRECTORIES)}"
            )

    # Check blocked extensions for write operations
    if for_write:
        ext = resolved.suffix.lower()
        if ext in BLOCKED_WRITE_EXTENSIONS:
            return False, f"Writing files with extension '{ext}' is not allowed"

    return True, ""


# =============================================================================
# URL SECURITY CONFIGURATION
# =============================================================================

# Private/internal IP ranges to block (SSRF protection)
_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 private
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]

# Hostnames to block
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "metadata.google.internal",  # Cloud metadata services
    "169.254.169.254",           # AWS/Azure/GCP metadata
}

# Allowed URL schemes
ALLOWED_URL_SCHEMES = {"http", "https"}


def is_url_safe(url: str) -> tuple[bool, str]:
    """Check if a URL is safe to access (not internal/SSRF target).
    
    Args:
        url: The URL to validate.
    
    Returns:
        Tuple of (is_safe, reason_if_blocked).
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    # Check scheme
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        return False, f"URL scheme '{scheme}' is not allowed. Allowed: {', '.join(ALLOWED_URL_SCHEMES)}"

    # Get hostname
    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"

    # Check blocked hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False, f"Access to '{hostname}' is blocked (internal/metadata endpoint)"

    # Check if hostname is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        for network in _PRIVATE_IP_RANGES:
            if ip in network:
                return False, f"Access to private/internal IP '{hostname}' is blocked"
    except ValueError:
        # Not an IP, it's a hostname - that's fine
        pass

    return True, ""


# =============================================================================
# APPLICATION EXECUTION CONFIGURATION
# =============================================================================

# Safe applications that can be opened directly
SAFE_APPLICATIONS: set[str] = {
    # Text editors
    "notepad", "notepad.exe", "wordpad", "wordpad.exe",
    # Calculators/utilities
    "calc", "calc.exe", "calculator",
    # Browsers (these are generally safe to open URLs with)
    "chrome", "firefox", "msedge", "edge",
    # Office applications
    "winword", "excel", "powerpnt", "outlook",
    # Media
    "mspaint", "paint", "snip",
}

# File extensions that are safe to open with default application
SAFE_OPEN_EXTENSIONS: set[str] = {
    # Documents
    ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".rtf", ".odt", ".ods", ".odp",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico",
    # Media
    ".mp3", ".mp4", ".wav", ".avi", ".mkv", ".webm", ".mov",
    # Web
    ".html", ".htm",
    # Data
    ".json", ".xml", ".csv", ".yaml", ".yml",
}

# URLs are always allowed to open (they use the default browser)


def is_execution_safe(app_name_or_path: str) -> tuple[bool, str]:
    """Check if opening an application/file is safe.
    
    Args:
        app_name_or_path: Application name, file path, or URL.
    
    Returns:
        Tuple of (is_safe, reason_if_blocked).
    """
    target = app_name_or_path.strip()
    lower = target.lower()

    # Allow URLs (they open in the browser)
    if lower.startswith("http://") or lower.startswith("https://"):
        return True, ""

    # Check if it's a known safe application name
    base_name = Path(target).name.lower()
    if base_name in SAFE_APPLICATIONS or lower in SAFE_APPLICATIONS:
        return True, ""

    # Check file extension (works for both existing and non-existing paths)
    try:
        path = Path(target)
        ext = path.suffix.lower()
        if ext:  # Has an extension
            if ext in SAFE_OPEN_EXTENSIONS:
                return True, ""
            else:
                return False, (
                    f"Opening files with extension '{ext}' is not allowed for security. "
                    f"Safe extensions: {', '.join(sorted(SAFE_OPEN_EXTENSIONS)[:10])}..."
                )
    except (OSError, ValueError):
        pass

    return False, (
        f"'{target}' is not a recognized safe application or file type. "
        f"Safe apps: {', '.join(sorted(list(SAFE_APPLICATIONS)[:5]))}..."
    )

"""Laptop Assistant MCP Server.

An MCP server that acts as a laptop assistant, providing tools for system
operations, file management, web browsing, application management, and
utility functions. Integrates with Claude Code and Google Antigravity.
"""

import json
import logging
import os
import sys

import psutil
from mcp.server.fastmcp import FastMCP

from src.http_client import http_lifespan, get_server_uptime
from src.perf import configure_logging

# Configure logging to stderr (NEVER stdout -- stdout is for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# Apply MCP_LOG_LEVEL env var
configure_logging()

logger = logging.getLogger(__name__)

# Create the MCP server instance with shared HTTP client lifespan
mcp = FastMCP("laptop-assistant", lifespan=http_lifespan)

# Register tool modules
from src.tools.system_tools import register_tools as register_system_tools  # noqa: E402
from src.tools.file_tools import register_tools as register_file_tools  # noqa: E402
from src.tools.web_tools import register_tools as register_web_tools  # noqa: E402
from src.tools.app_tools import register_tools as register_app_tools  # noqa: E402
from src.tools.utility_tools import register_tools as register_utility_tools  # noqa: E402
from src.tools.desktop_tools import register_tools as register_desktop_tools  # noqa: E402
from src.safety import register_confirmation_tool  # noqa: E402

register_system_tools(mcp)
register_file_tools(mcp)
register_web_tools(mcp)
register_app_tools(mcp)
register_utility_tools(mcp)
register_desktop_tools(mcp)
register_confirmation_tool(mcp)


# ---------------------------------------------------------------------------
# Health check resource
# ---------------------------------------------------------------------------
@mcp.resource("server://health")
def server_health() -> str:
    """Server health status: uptime, memory usage, and registered tool count."""
    mem = psutil.virtual_memory()
    process = psutil.Process()
    uptime = get_server_uptime()

    hours, remainder = divmod(int(uptime), 3600)
    minutes, seconds = divmod(remainder, 60)

    return json.dumps({
        "status": "healthy",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": round(uptime, 1),
        "server_memory_mb": round(process.memory_info().rss / (1024 ** 2), 1),
        "system_memory_percent": mem.percent,
        "tool_count": len(mcp._tool_manager._tools),
    }, indent=2)


logger.info("Laptop Assistant MCP server initialized with all tools registered.")


def main():
    """Run the MCP server with configurable transport.

    Set the MCP_TRANSPORT environment variable to choose transport:
        - stdio (default)
        - sse
        - streamable-http
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    valid_transports = {"stdio", "sse", "streamable-http"}

    if transport not in valid_transports:
        logger.warning(
            "Invalid MCP_TRANSPORT '%s', falling back to stdio. Valid: %s",
            transport,
            ", ".join(valid_transports),
        )
        transport = "stdio"

    logger.info("Starting Laptop Assistant MCP server (%s transport)...", transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()

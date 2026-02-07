"""Laptop Assistant MCP Server.

An MCP server that acts as a laptop assistant, providing tools for system
operations, file management, web browsing, application management, and
utility functions. Integrates with Claude Code and Google Antigravity.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (NEVER stdout -- stdout is for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

# Create the MCP server instance
mcp = FastMCP("laptop-assistant")

# Register tool modules
from src.tools.system_tools import register_tools as register_system_tools  # noqa: E402
from src.tools.file_tools import register_tools as register_file_tools  # noqa: E402
from src.tools.web_tools import register_tools as register_web_tools  # noqa: E402
from src.tools.app_tools import register_tools as register_app_tools  # noqa: E402
from src.tools.utility_tools import register_tools as register_utility_tools  # noqa: E402
from src.safety import register_confirmation_tool  # noqa: E402

register_system_tools(mcp)
register_file_tools(mcp)
register_web_tools(mcp)
register_app_tools(mcp)
register_utility_tools(mcp)
register_confirmation_tool(mcp)

logger.info("Laptop Assistant MCP server initialized with all tools registered.")


def main():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Laptop Assistant MCP server (stdio transport)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

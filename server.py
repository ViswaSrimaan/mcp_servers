"""Laptop Assistant MCP Server.

An MCP server that acts as a laptop assistant, providing tools for system
operations, file management, web browsing, application management, and
utility functions. Integrates with Claude Code and Google Antigravity.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from src.tools import (
    system_tools,
    file_tools,
    web_tools,
    app_tools,
    utility_tools,
    desktop_tools,
)
from src.safety import register_confirmation_tool

# Configure logging to stderr (NEVER stdout -- stdout is for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)

# Create the MCP server instance
mcp = FastMCP("laptop-assistant")


# Register tools
system_tools.register_tools(mcp)
file_tools.register_tools(mcp)
web_tools.register_tools(mcp)
app_tools.register_tools(mcp)
utility_tools.register_tools(mcp)
desktop_tools.register_tools(mcp)
register_confirmation_tool(mcp)


logger.info("Laptop Assistant MCP server initialized with all tools registered.")


def main():
    """Run the MCP server with stdio transport."""
    logger.info("Starting Laptop Assistant MCP server (stdio transport)...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

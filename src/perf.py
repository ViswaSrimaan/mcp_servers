"""Performance monitoring utilities for the MCP server.

Provides a decorator that logs tool execution time and a configurable
log-level reader.
"""

import functools
import logging
import os
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable log level via environment variable
# ---------------------------------------------------------------------------
_LOG_LEVEL = os.environ.get("MCP_LOG_LEVEL", "INFO").upper()


def configure_logging() -> None:
    """Apply the MCP_LOG_LEVEL environment variable to the root logger."""
    numeric = getattr(logging, _LOG_LEVEL, logging.INFO)
    logging.getLogger().setLevel(numeric)
    logger.debug("Log level set to %s", _LOG_LEVEL)


# ---------------------------------------------------------------------------
# @timed decorator
# ---------------------------------------------------------------------------
def timed(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that logs execution time of an async tool function.

    Logs at INFO level with the function name, elapsed time, and whether
    the call succeeded or raised an exception.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        tool_name = fn.__name__
        try:
            result = await fn(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info("⏱  %s completed in %.3fs", tool_name, elapsed)
            return result
        except Exception:
            elapsed = time.perf_counter() - start
            logger.error("⏱  %s failed after %.3fs", tool_name, elapsed)
            raise

    return wrapper

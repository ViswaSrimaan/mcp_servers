"""Shared HTTP client with connection pooling and retry logic.

Provides a long-lived httpx.AsyncClient that is reused across all web tool
calls, avoiding the overhead of creating/destroying connections per request.
Includes a retry helper with exponential backoff for transient failures.
"""

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common headers shared across all HTTP requests
# ---------------------------------------------------------------------------
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Module-level singleton — set during lifespan
# ---------------------------------------------------------------------------
_client: httpx.AsyncClient | None = None
_server_start_time: float | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared HTTP client.

    Raises:
        RuntimeError: If called before the server lifespan has started.
    """
    if _client is None:
        raise RuntimeError(
            "HTTP client not initialised — the server lifespan has not started."
        )
    return _client


def get_server_uptime() -> float:
    """Return server uptime in seconds, or 0 if not started."""
    if _server_start_time is None:
        return 0.0
    return time.time() - _server_start_time


# ---------------------------------------------------------------------------
# Lifespan context manager for FastMCP
# ---------------------------------------------------------------------------
@asynccontextmanager
async def http_lifespan(app: Any) -> AsyncIterator[None]:
    """FastMCP lifespan that manages the shared HTTP client."""
    global _client, _server_start_time  # noqa: PLW0603

    _server_start_time = time.time()

    _client = httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=60,
        ),
    )
    logger.info("Shared HTTP client created (pool: 20 max, 10 keepalive)")

    try:
        yield
    finally:
        await _client.aclose()
        _client = None
        logger.info("Shared HTTP client closed")


# ---------------------------------------------------------------------------
# Retry helper with exponential backoff + jitter
# ---------------------------------------------------------------------------
# HTTP status codes that are safe to retry
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


async def retry_request(
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    **kwargs: Any,
) -> httpx.Response:
    """Execute an HTTP request with automatic retries on transient failures.

    Args:
        method: HTTP method ('GET', 'POST', etc.).
        url: Target URL.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Initial backoff delay in seconds (default 0.5).
        max_delay: Maximum backoff delay in seconds (default 10).
        **kwargs: Additional arguments passed to ``httpx.AsyncClient.request``.

    Returns:
        The successful ``httpx.Response``.

    Raises:
        httpx.HTTPStatusError: If all retries are exhausted with HTTP errors.
        httpx.TimeoutException: If all retries are exhausted with timeouts.
        Exception: Any non-retryable error from httpx.
    """
    client = get_client()
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)

            if response.status_code not in _RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response

            # Retryable HTTP status
            last_exception = httpx.HTTPStatusError(
                f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
            logger.warning(
                "HTTP %d from %s (attempt %d/%d)",
                response.status_code,
                url,
                attempt,
                max_retries,
            )

        except httpx.TimeoutException as exc:
            last_exception = exc
            logger.warning(
                "Timeout requesting %s (attempt %d/%d)", url, attempt, max_retries
            )

        except httpx.HTTPStatusError:
            raise  # non-retryable HTTP error — let caller handle

        except Exception as exc:
            # Network-level errors (DNS, connection refused, etc.)
            last_exception = exc
            logger.warning(
                "Network error requesting %s: %s (attempt %d/%d)",
                url,
                exc,
                attempt,
                max_retries,
            )

        if attempt < max_retries:
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            jitter = random.uniform(0, delay * 0.5)  # noqa: S311
            await asyncio.sleep(delay + jitter)

    # All retries exhausted
    assert last_exception is not None
    raise last_exception

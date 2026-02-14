"""Web browsing tools for the Laptop Assistant MCP server.

Provides tools for web searching, fetching webpage content, and downloading files.
Uses the shared HTTP client for connection pooling and retry logic.
"""

import json
import logging
from pathlib import Path

from bs4 import BeautifulSoup
from mcp.server.fastmcp import Context

from src.http_client import get_client, retry_request
from src.perf import timed
from src.security_config import is_url_safe, is_path_allowed

logger = logging.getLogger(__name__)


def register_tools(mcp) -> None:
    """Register all web tools with the MCP server."""

    @mcp.tool()
    @timed
    async def web_search(query: str, num_results: int = 5) -> str:
        """Search the web using DuckDuckGo and return results.

        Args:
            query: The search query.
            num_results: Number of results to return (default: 5, max: 20).
        """
        num_results = min(max(num_results, 1), 20)

        # Note: DuckDuckGo is a trusted search engine, no SSRF check needed here
        try:
            response = await retry_request(
                "GET",
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=15.0,
            )

            soup = BeautifulSoup(response.text, "html.parser")
            results = []

            for result_div in soup.select(".result")[:num_results]:
                title_el = result_div.select_one(".result__a")
                snippet_el = result_div.select_one(".result__snippet")

                if title_el:
                    href = title_el.get("href", "")
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "url": href,
                        "snippet": (
                            snippet_el.get_text(strip=True) if snippet_el else ""
                        ),
                    })

            return json.dumps({
                "query": query,
                "num_results": len(results),
                "results": results,
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Search failed: {e}",
            })

    @mcp.tool()
    @timed
    async def fetch_webpage(url: str, extract_text: bool = True) -> str:
        """Fetch a webpage and return its content.

        Args:
            url: The URL to fetch.
            extract_text: If True, extract clean text from HTML. If False, return raw HTML (default: True).
        """
        # Security: Validate URL to prevent SSRF
        safe, reason = is_url_safe(url)
        if not safe:
            return json.dumps({
                "status": "error",
                "message": f"URL blocked for security: {reason}",
            })

        try:
            response = await retry_request("GET", url, timeout=30.0)

            content_type = response.headers.get("content-type", "")

            if extract_text and "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")

                # Remove script and style elements
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()

                text = soup.get_text(separator="\n", strip=True)

                # Clean up excessive whitespace
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                text = "\n".join(lines)

                # Truncate if too long
                if len(text) > 10000:
                    text = text[:10000] + "\n\n... (content truncated)"

                return json.dumps({
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "text": text,
                }, indent=2)
            else:
                # Return raw content (truncated)
                raw = response.text
                if len(raw) > 15000:
                    raw = raw[:15000] + "\n\n... (content truncated)"

                return json.dumps({
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "content": raw,
                }, indent=2)

        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to fetch webpage: {e}",
            })

    @mcp.tool()
    @timed
    async def download_file(url: str, save_path: str, ctx: Context = None) -> str:
        """Download a file from a URL to a local path.

        Args:
            url: The URL of the file to download.
            save_path: The local path to save the downloaded file.
        """
        import asyncio

        # Security: Validate URL to prevent SSRF
        safe, reason = is_url_safe(url)
        if not safe:
            return json.dumps({
                "status": "error",
                "message": f"URL blocked for security: {reason}",
            })

        target = Path(save_path).resolve()

        # Security: Validate save path
        allowed, reason = is_path_allowed(target, for_write=True)
        if not allowed:
            return json.dumps({
                "status": "error",
                "message": f"Save path blocked for security: {reason}",
            })

        try:
            await asyncio.to_thread(lambda: target.parent.mkdir(parents=True, exist_ok=True))

            client = get_client()
            async with client.stream("GET", url, timeout=120.0) as response:
                response.raise_for_status()

                content_length = response.headers.get("content-length")
                total = int(content_length) if content_length else None

                # Collect chunks with progress reporting
                chunks = []
                downloaded = 0
                chunk_count = 0
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    chunk_count += 1

                    # Report progress every 10 chunks (~80KB)
                    if ctx and chunk_count % 10 == 0:
                        try:
                            await ctx.report_progress(
                                progress=downloaded,
                                total=total or 0,
                            )
                        except Exception:
                            pass  # progress reporting is best-effort

                def _write_file():
                    with open(target, "wb") as f:
                        for c in chunks:
                            f.write(c)
                    return sum(len(c) for c in chunks)

                total_size = await asyncio.to_thread(_write_file)

            # Final progress report
            if ctx:
                try:
                    await ctx.report_progress(progress=total_size, total=total_size)
                except Exception:
                    pass

            from src.tools.file_tools import _format_size

            return json.dumps({
                "status": "success",
                "message": "File downloaded successfully.",
                "url": url,
                "save_path": str(target),
                "size": _format_size(total_size),
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Download failed: {e}",
            })

"""Web browsing tools for the Laptop Assistant MCP server.

Provides tools for web searching, fetching webpage content, and downloading files.
"""

import json
import logging
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Common headers to avoid being blocked
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def register_tools(mcp) -> None:
    """Register all web tools with the MCP server."""

    @mcp.tool()
    async def web_search(query: str, num_results: int = 5) -> str:
        """Search the web using DuckDuckGo and return results.

        Args:
            query: The search query.
            num_results: Number of results to return (default: 5, max: 20).
        """
        num_results = min(max(num_results, 1), 20)

        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=15.0
            ) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )
                response.raise_for_status()

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

        except httpx.TimeoutException:
            return json.dumps({
                "status": "error",
                "message": "Search request timed out. Please try again.",
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Search failed: {e}",
            })

    @mcp.tool()
    async def fetch_webpage(url: str, extract_text: bool = True) -> str:
        """Fetch a webpage and return its content.

        Args:
            url: The URL to fetch.
            extract_text: If True, extract clean text from HTML. If False, return raw HTML (default: True).
        """
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=30.0
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

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

        except httpx.TimeoutException:
            return json.dumps({
                "status": "error",
                "message": f"Request to {url} timed out.",
            })
        except httpx.HTTPStatusError as e:
            return json.dumps({
                "status": "error",
                "message": f"HTTP error {e.response.status_code} fetching {url}.",
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to fetch webpage: {e}",
            })

    @mcp.tool()
    async def download_file(url: str, save_path: str) -> str:
        """Download a file from a URL to a local path.

        Args:
            url: The URL of the file to download.
            save_path: The local path to save the downloaded file.
        """
        target = Path(save_path).resolve()

        try:
            target.parent.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=120.0
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()

                    total_size = 0
                    with open(target, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            total_size += len(chunk)

            from src.tools.file_tools import _format_size

            return json.dumps({
                "status": "success",
                "message": "File downloaded successfully.",
                "url": url,
                "save_path": str(target),
                "size": _format_size(total_size),
            }, indent=2)

        except httpx.TimeoutException:
            return json.dumps({
                "status": "error",
                "message": f"Download timed out for {url}.",
            })
        except httpx.HTTPStatusError as e:
            return json.dumps({
                "status": "error",
                "message": f"HTTP error {e.response.status_code} downloading {url}.",
            })
        except Exception as e:
            return json.dumps({
                "status": "error",
                "message": f"Download failed: {e}",
            })

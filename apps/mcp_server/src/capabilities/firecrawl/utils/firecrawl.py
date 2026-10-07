"""Minimal Firecrawl API client (https://docs.firecrawl.dev/api-reference). Scrape, map and crawl only."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

HOSTED_URL = "https://api.firecrawl.dev"
TIMEOUT_SECONDS = 60
POLL_SECONDS = 2.0


class FirecrawlError(RuntimeError):
    """Firecrawl refused the request or could not be reached."""


class FirecrawlClient:
    """Blocking client. Callers run it off the event loop (see `@offload`).

    The hosted API needs a key. A self-hosted instance (custom `base_url`)
    may run without one, so the key is only required for the hosted address.
    """

    def __init__(self, api_key: str, base_url: str = "", timeout: int = TIMEOUT_SECONDS) -> None:
        self._base_url = (base_url or HOSTED_URL).rstrip("/")
        if not api_key and self._base_url == HOSTED_URL:
            raise FirecrawlError("FIRECRAWL_API_KEY is not set. Add it to apps/mcp_server/.env and restart the server.")
        self._api_key = api_key
        self._timeout = timeout

    def scrape(self, url: str) -> dict:
        """The page for `url`: {"markdown", "metadata"}."""
        body = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
        return self._request("POST", "/v2/scrape", body).get("data") or {}

    def map(self, url: str, limit: int) -> list[dict]:
        """Site links as [{"url", "title"}]; accepts both plain-string and object links."""
        links = self._request("POST", "/v2/map", {"url": url, "limit": limit}).get("links") or []
        return [{"url": link} if isinstance(link, str) else link for link in links]

    def crawl(self, url: str, limit: int, wait_seconds: float) -> tuple[str, list[dict]]:
        """Start a crawl and poll up to `wait_seconds`. Returns (status, pages so far)."""
        body = {"url": url, "limit": limit, "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
        job = self._request("POST", "/v2/crawl", body).get("id")
        if not job:
            raise FirecrawlError("Firecrawl did not return a crawl id.")
        deadline = time.monotonic() + wait_seconds
        while True:
            state = self._request("GET", f"/v2/crawl/{job}")
            status = state.get("status", "scraping")
            if status != "scraping" or time.monotonic() >= deadline:
                return status, state.get("data") or []
            time.sleep(POLL_SECONDS)

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - base URL comes from config, not a caller
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise FirecrawlError(f"Firecrawl answered HTTP {error.code}{_hint(error.code)}.") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise FirecrawlError(f"Could not reach Firecrawl: {error}") from error
        if data.get("success") is False:
            raise FirecrawlError(f"Firecrawl failed: {data.get('error') or 'unknown error'}.")
        return data


def _hint(code: int) -> str:
    return {
        401: " - the API key was rejected",
        402: " - out of credits",
        429: " - rate limit reached",
    }.get(code, "")

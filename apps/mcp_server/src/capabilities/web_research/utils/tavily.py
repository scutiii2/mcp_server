"""Minimal Tavily API client (https://docs.tavily.com). Search and extract only."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE_URL = "https://api.tavily.com"
TIMEOUT_SECONDS = 30


class TavilyError(RuntimeError):
    """Tavily refused the request or could not be reached."""


class TavilyClient:
    """Blocking client. Callers run it off the event loop (see `@offload`)."""

    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: int = TIMEOUT_SECONDS) -> None:
        if not api_key:
            raise TavilyError("TAVILY_API_KEY is not set. Add it to apps/mcp_server/.env and restart the server.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(self, query: str, max_results: int, topic: str) -> list[dict]:
        body = {
            "query": query,
            "max_results": max_results,
            "topic": topic,
            "search_depth": "basic",
            "include_answer": False,  # tools never call an AI; the agent writes the answer
        }
        return self._post("/search", body).get("results", [])

    def extract(self, url: str) -> dict:
        """The page text for `url`: {"url", "raw_content"}; raises TavilyError if it failed."""
        data = self._post("/extract", {"urls": [url]})
        for page in data.get("results", []):
            return page
        failed = data.get("failed_results") or []
        reason = failed[0].get("error") if failed else "no content returned"
        raise TavilyError(f"Could not read {url}: {reason}")

    def _post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - fixed https base URL
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise TavilyError(f"Tavily answered HTTP {error.code}{_hint(error.code)}.") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise TavilyError(f"Could not reach Tavily: {error}") from error


def _hint(code: int) -> str:
    return {
        401: " - the API key was rejected",
        429: " - rate limit or plan limit reached",
        432: " - plan limit reached",
        433: " - plan limit reached",
    }.get(code, "")

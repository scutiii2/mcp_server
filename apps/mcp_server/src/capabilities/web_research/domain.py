"""Search the web and read pages through Tavily.

Tavily fetches the pages, so this server never opens a connection to an
address a caller chose. Web text is capped and fenced (`services/untrusted.py`)
before it is returned: it reaches a model, and a page can say anything.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.capabilities.web_research.contract import PageResult, SearchHit, SearchResult
from src.capabilities.web_research.utils.tavily import TavilyClient
from src.services import untrusted

MAX_RESULTS = 10
MAX_PAGE_BYTES = 24_000
MAX_SNIPPET_CHARS = 600
TOPICS = ("general", "news")


def search(client: TavilyClient, query: str, max_results: int = 5, topic: str = "general") -> SearchResult:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}, not {max_results}")
    if topic not in TOPICS:
        raise ValueError(f"topic must be one of {', '.join(TOPICS)}, not {topic!r}")
    hits = [
        SearchHit(
            title=item.get("title") or item["url"],
            url=item["url"],
            snippet=_snippet(item.get("content") or ""),
            score=round(float(item.get("score") or 0.0), 3),
        )
        for item in client.search(query, max_results, topic)
        if item.get("url")
    ]
    message = f"{len(hits)} results for {query!r}." if hits else f"No results for {query!r}."
    return SearchResult(query=query, results=hits, message=message)


def read_page(client: TavilyClient, url: str) -> PageResult:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"url must start with http:// or https://, not {url!r}")
    page = client.extract(url)
    text = page.get("raw_content") or ""
    if not text.strip():
        return PageResult(url=url, content="", message=f"{url} returned no readable text.")
    content = untrusted.fenced_and_capped(text, source=f"web page {url}", max_bytes=MAX_PAGE_BYTES)
    return PageResult(url=url, content=content, message=f"Read {url} ({len(text)} characters).")


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SNIPPET_CHARS else text[: MAX_SNIPPET_CHARS - 3] + "..."

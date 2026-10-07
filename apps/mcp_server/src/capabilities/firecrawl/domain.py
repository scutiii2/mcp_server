"""Scrape pages, map sites and crawl them through Firecrawl.

Firecrawl fetches the pages, so this server never opens a connection to an
address a caller chose. Web text is capped and fenced (`services/untrusted.py`)
before it is returned: it reaches a model, and a page can say anything.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.capabilities.firecrawl.contract import CrawlResult, MapResult, ScrapeResult, SiteLink
from src.capabilities.firecrawl.utils.firecrawl import FirecrawlClient
from src.services import untrusted

MAX_PAGE_BYTES = 24_000
MAX_CRAWL_BYTES = 48_000
MAX_MAP_LINKS = 500
MAX_CRAWL_PAGES = 25
CRAWL_WAIT_SECONDS = 60.0


def scrape_page(client: FirecrawlClient, url: str) -> ScrapeResult:
    url = _check_url(url)
    page = client.scrape(url)
    text = page.get("markdown") or ""
    title = (page.get("metadata") or {}).get("title") or ""
    if not text.strip():
        return ScrapeResult(url=url, title=title, content="", message=f"{url} returned no readable text.")
    content = untrusted.fenced_and_capped(text, source=f"web page {url}", max_bytes=MAX_PAGE_BYTES)
    return ScrapeResult(url=url, title=title, content=content, message=f"Scraped {url} ({len(text)} characters).")


def map_site(client: FirecrawlClient, url: str, limit: int = 100) -> MapResult:
    url = _check_url(url)
    _check_limit(limit, MAX_MAP_LINKS)
    links = [
        SiteLink(url=item["url"], title=item.get("title") or "")
        for item in client.map(url, limit)
        if item.get("url")
    ]
    message = f"{len(links)} pages found on {url}." if links else f"No pages found on {url}."
    return MapResult(url=url, links=links, message=message)


def crawl_site(client: FirecrawlClient, url: str, limit: int = 10, wait_seconds: float = CRAWL_WAIT_SECONDS) -> CrawlResult:
    url = _check_url(url)
    _check_limit(limit, MAX_CRAWL_PAGES)
    status, raw_pages = client.crawl(url, limit, wait_seconds)
    if status == "failed":
        raise ValueError(f"The crawl of {url} failed on Firecrawl's side.")
    pages: list[str] = []
    sections: list[str] = []
    for item in raw_pages:
        text = item.get("markdown") or ""
        if not text.strip():
            continue
        meta = item.get("metadata") or {}
        address = meta.get("sourceURL") or meta.get("url") or "(unknown address)"
        pages.append(address)
        sections.append(f"## {address}\n{text}")
    joined = "\n\n".join(sections)
    content = untrusted.fenced_and_capped(joined, source=f"crawl of {url}", max_bytes=MAX_CRAWL_BYTES) if joined else ""
    suffix = "" if status == "completed" else " The crawl is still running; call again later or lower the limit."
    return CrawlResult(url=url, status=status, pages=pages, content=content, message=f"Crawled {len(pages)} pages from {url}.{suffix}")


def _check_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"url must start with http:// or https://, not {url!r}")
    return url


def _check_limit(limit: int, maximum: int) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}, not {limit}")

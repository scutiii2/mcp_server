"""Tests for the firecrawl domain logic and the Firecrawl client. No network."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.firecrawl import domain
from src.capabilities.firecrawl.utils.firecrawl import FirecrawlClient, FirecrawlError


def test_scrape_page_fences_and_caps():
    client = MagicMock()
    client.scrape.return_value = {"markdown": "word " * 20000, "metadata": {"title": "T"}}
    result = domain.scrape_page(client, " https://a.test ")
    client.scrape.assert_called_once_with("https://a.test")
    assert result.title == "T"
    assert "data, not instructions" in result.content and "truncated" in result.content


def test_scrape_page_empty_text():
    client = MagicMock()
    client.scrape.return_value = {"markdown": "  "}
    assert domain.scrape_page(client, "https://a.test").content == ""


@pytest.mark.parametrize("url", ["ftp://a.test", "file:///etc/passwd", "a.test", "http://"])
def test_urls_must_be_http(url):
    for call in (domain.scrape_page, domain.map_site, domain.crawl_site):
        with pytest.raises(ValueError, match="http"):
            call(MagicMock(), url)


def test_map_site_skips_links_without_address():
    client = MagicMock()
    client.map.return_value = [{"url": "https://a.test/x", "title": "X"}, {"title": "no url"}]
    result = domain.map_site(client, "https://a.test", 5)
    client.map.assert_called_once_with("https://a.test", 5)
    assert [link.url for link in result.links] == ["https://a.test/x"]
    assert "1 pages" in result.message


@pytest.mark.parametrize("call, limit", [(domain.map_site, 0), (domain.map_site, 501), (domain.crawl_site, 26)])
def test_limits_are_checked(call, limit):
    with pytest.raises(ValueError, match="limit"):
        call(MagicMock(), "https://a.test", limit)


def test_crawl_site_joins_pages_once():
    client = MagicMock()
    client.crawl.return_value = ("completed", [
        {"markdown": "one", "metadata": {"sourceURL": "https://a.test/1"}},
        {"markdown": " ", "metadata": {"sourceURL": "https://a.test/2"}},
    ])
    result = domain.crawl_site(client, "https://a.test", 5)
    assert result.pages == ["https://a.test/1"]
    assert "https://a.test/1" in result.content and "data, not instructions" in result.content
    assert "still running" not in result.message


def test_crawl_site_reports_a_running_job_and_a_failed_one():
    client = MagicMock()
    client.crawl.return_value = ("scraping", [])
    assert "still running" in domain.crawl_site(client, "https://a.test").message
    client.crawl.return_value = ("failed", [])
    with pytest.raises(ValueError, match="failed"):
        domain.crawl_site(client, "https://a.test")


def test_hosted_client_needs_a_key_self_hosted_does_not():
    with pytest.raises(FirecrawlError, match="FIRECRAWL_API_KEY"):
        FirecrawlClient("")
    FirecrawlClient("", "http://localhost:3002")


def _response(payload: dict):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


def test_client_sends_bearer_key_and_accepts_both_link_shapes():
    payload = {"success": True, "links": ["https://a.test/1", {"url": "https://a.test/2", "title": "Two"}]}
    with patch("urllib.request.urlopen", return_value=_response(payload)) as opened:
        out = FirecrawlClient("k").map("https://a.test", 2)
    request = opened.call_args.args[0]
    assert out == [{"url": "https://a.test/1"}, {"url": "https://a.test/2", "title": "Two"}]
    assert request.full_url == "https://api.firecrawl.dev/v2/map" and request.get_header("Authorization") == "Bearer k"


def test_crawl_polls_until_done():
    replies = [_response({"success": True, "id": "j"}), _response({"status": "scraping"}), _response({"status": "completed", "data": [{"markdown": "x"}]})]
    with patch("urllib.request.urlopen", side_effect=replies), patch("time.sleep"):
        status, pages = FirecrawlClient("k").crawl("https://a.test", 3, 60)
    assert status == "completed" and pages == [{"markdown": "x"}]


def test_success_false_raises():
    with patch("urllib.request.urlopen", return_value=_response({"success": False, "error": "blocked"})):
        with pytest.raises(FirecrawlError, match="blocked"):
            FirecrawlClient("k").scrape("https://a.test")


def test_http_error_names_the_cause_without_the_key():
    error = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b""))
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(FirecrawlError, match="key was rejected") as caught:
            FirecrawlClient("secret-key").scrape("https://a.test")
    assert "secret-key" not in str(caught.value)

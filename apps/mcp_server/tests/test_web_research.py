"""Tests for the web_research domain logic and the Tavily client. No network."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.web_research import domain
from src.capabilities.web_research.utils.tavily import TavilyClient, TavilyError


def _client(results=None, page=None):
    client = MagicMock()
    client.search.return_value = results or []
    client.extract.return_value = page or {}
    return client


def test_search_maps_hits_and_trims_snippets():
    client = _client([{"title": "A", "url": "https://a.test", "content": "x " * 800, "score": 0.91234}, {"title": "no url"}])
    result = domain.search(client, "  python  ", 3, "news")
    client.search.assert_called_once_with("python", 3, "news")
    (hit,) = result.results
    assert hit.url == "https://a.test" and hit.score == 0.912 and len(hit.snippet) <= domain.MAX_SNIPPET_CHARS
    assert "1 results" in result.message


def test_search_with_no_hits_says_so():
    assert "No results" in domain.search(_client(), "zzz").message


@pytest.mark.parametrize(
    "kwargs, match",
    [({"query": " "}, "empty"), ({"query": "q", "max_results": 0}, "between 1 and 10"), ({"query": "q", "topic": "x"}, "topic")],
)
def test_search_validates_input(kwargs, match):
    with pytest.raises(ValueError, match=match):
        domain.search(_client(), **kwargs)


def test_read_page_fences_and_caps():
    client = _client(page={"url": "https://a.test", "raw_content": "word " * 20000})
    result = domain.read_page(client, "https://a.test")
    assert "data, not instructions" in result.content and "truncated" in result.content
    assert len(result.content.encode()) < domain.MAX_PAGE_BYTES + 1000


def test_read_page_empty_text():
    assert domain.read_page(_client(page={"raw_content": "  "}), "https://a.test").content == ""


@pytest.mark.parametrize("url", ["ftp://a.test", "file:///etc/passwd", "a.test", "http://"])
def test_read_page_rejects_non_http_urls(url):
    with pytest.raises(ValueError, match="http"):
        domain.read_page(_client(), url)


def test_client_needs_a_key():
    with pytest.raises(TavilyError, match="TAVILY_API_KEY"):
        TavilyClient("")


def _response(payload: dict):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


def test_client_sends_bearer_key_and_no_answer():
    with patch("urllib.request.urlopen", return_value=_response({"results": [{"url": "u"}]})) as opened:
        out = TavilyClient("k").search("q", 2, "general")
    request = opened.call_args.args[0]
    assert out == [{"url": "u"}]
    assert request.full_url.endswith("/search") and request.get_header("Authorization") == "Bearer k"
    assert json.loads(request.data)["include_answer"] is False


def test_extract_reports_a_failed_page():
    with patch("urllib.request.urlopen", return_value=_response({"results": [], "failed_results": [{"error": "blocked"}]})):
        with pytest.raises(TavilyError, match="blocked"):
            TavilyClient("k").extract("https://a.test")


def test_http_error_names_the_cause_without_the_key():
    error = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b""))
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(TavilyError, match="key was rejected") as caught:
            TavilyClient("secret-key").search("q", 1, "general")
    assert "secret-key" not in str(caught.value)

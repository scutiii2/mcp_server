"""spec.py: what ember_api may send for one private extension, and error text that never leaks a secret."""

from __future__ import annotations

import httpx
import pytest

from src.private_extensions.guard import BlockedAddress, RedirectRefused
from src.private_extensions.spec import InvalidSpec, PrivateSpec, describe_error

GOOD = {"id": "notes", "label": "My notes", "url": "https://notes.example.com/mcp", "headers": {"X-Api-Key": "abc123"}}


def test_a_good_spec_parses():
    spec = PrivateSpec.parse(GOOD)

    assert (spec.slug, spec.label, spec.url) == ("notes", "My notes", "https://notes.example.com/mcp")
    assert spec.header_map == {"X-Api-Key": "abc123"}
    assert spec.host == "notes.example.com"
    assert spec.secrets == ("abc123",)


def test_headers_are_optional_and_the_label_defaults_to_the_slug():
    spec = PrivateSpec.parse({"id": "a1", "url": "http://10.0.0.5:8000/mcp"})

    assert spec.header_map == {}
    assert spec.label == "a1"


@pytest.mark.parametrize("bad", ["", "Notes", "a__b", "_a", "a_", "a b", "x" * 41, 5, None])
def test_bad_slugs_are_refused(bad):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "id": bad})


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x.com/mcp", "notes.example.com", "https:///mcp", "https://user:pw@x.com/mcp", "https://x.com/" + "a" * 1000, 5, None],
)
def test_bad_urls_are_refused(url):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "url": url})


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil"}, {"cookie": "a=b"}, {"Content-Length": "5"}, {"bad name": "v"}, {"X": ""}, {"X": "a\nb"},
        {"X": "a" * 2001}, {f"H{i}": "v" for i in range(21)}, {"X": 5}, ["X", "v"],
    ],
)
def test_bad_headers_are_refused(headers):
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse({**GOOD, "headers": headers})


def test_a_non_object_is_refused():
    with pytest.raises(InvalidSpec):
        PrivateSpec.parse("https://x.com")


def test_the_key_changes_with_the_url_or_headers_and_not_with_header_order():
    a = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "2"}})
    b = PrivateSpec.parse({**GOOD, "headers": {"B": "2", "A": "1"}})
    c = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "3"}})
    d = PrivateSpec.parse({**GOOD, "headers": {"A": "1", "B": "2"}, "url": "https://other.example.com/mcp"})

    assert a.key() == b.key()
    assert len({a.key(), c.key(), d.key()}) == 3


def test_a_probe_spec_is_validated_the_same_way():
    spec = PrivateSpec.from_probe("https://x.example.com/mcp", {"Authorization": "Bearer t0ken"})

    assert spec.secrets == ("Bearer t0ken",)
    with pytest.raises(InvalidSpec):
        PrivateSpec.from_probe("file:///etc/passwd", None)


def test_describe_error_uses_the_safe_messages_as_they_are():
    assert describe_error(BlockedAddress()) == "That address is not allowed"
    assert "redirects to another host" in describe_error(RedirectRefused())


def test_describe_error_hides_secrets_and_keeps_one_short_line():
    error = RuntimeError("401 for header Bearer t0ken at host\nsecond line with t0ken")

    text = describe_error(error, ["Bearer t0ken", "t0ken"])

    assert "t0ken" not in text
    assert "\n" not in text
    assert "***" in text
    assert len(describe_error(RuntimeError("x" * 500))) <= 200


def test_describe_error_unwraps_exception_groups_and_names_timeouts():
    assert describe_error(BaseExceptionGroup("g", [BlockedAddress()])) == "That address is not allowed"
    assert describe_error(httpx.ReadTimeout("slow")) == "Timed out"
    assert describe_error(TimeoutError()) == "Timed out"
    assert describe_error(RuntimeError()) == "RuntimeError"

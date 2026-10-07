"""Tests for log redaction and the readable-log domain function."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.server_manager import domain
from src.capabilities.server_manager.utils.redact import MASK, redact


@pytest.mark.parametrize(
    "line, secret",
    [
        ("connect postgres://app:hunter2@db:5432/x", "hunter2"),
        ("Authorization: Bearer abcdef123456789", "abcdef123456789"),
        ("password=swordfish retry", "swordfish"),
        ('{"api_key": "sk-live-abcdefghijklmnop"}', "sk-live-abcdefghijklmnop"),
        ("token: eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4", "eyJhbGciOiJI"),
        ("key AKIAIOSFODNN7EXAMPLE used", "AKIAIOSFODNN7EXAMPLE"),
        ("login by jo.doe@example.com failed", "jo.doe@example.com"),
    ],
)
def test_secrets_are_masked(line, secret):
    text, count = redact(line)
    assert secret not in text and MASK in text and count >= 1


def test_plain_lines_are_untouched():
    line = "2026-01-01T00:00:00Z ERROR worker crashed: KeyError 'user'"
    assert redact(line) == (line, 0)


def _client_with_logs(output: bytes):
    container = MagicMock()
    container.name = "web"
    container.logs.return_value = output
    client = MagicMock()
    client.containers.get.return_value = container
    return client, container


def test_read_returns_masked_text():
    client, container = _client_with_logs(b"a ok\nb password=x1\n")
    with patch("docker.from_env", return_value=client):
        result = domain.read_app_logs("web", 50)
    container.logs.assert_called_once_with(tail=50, timestamps=True)
    assert result.lines == 2 and result.redactions == 1 and "x1" not in result.text


def test_contains_filters_and_searches_the_wide_tail():
    client, container = _client_with_logs(b"ok 1\nERROR a\nok 2\nerror b\n")
    with patch("docker.from_env", return_value=client):
        result = domain.read_app_logs("web", 1, contains="Error")
    assert container.logs.call_args.kwargs["tail"] == domain.MAX_LOG_LINES
    assert result.text.endswith("error b") and result.lines == 1


def test_empty_log_is_reported():
    client, _ = _client_with_logs(b"")
    with patch("docker.from_env", return_value=client):
        assert domain.read_app_logs("web").lines == 0


def test_text_is_capped_at_a_line_start():
    client, _ = _client_with_logs(("x" * 99 + "\n") * 300)
    client.containers.get.return_value.logs.return_value = ("x" * 99 + "\n").encode() * 300
    with patch("docker.from_env", return_value=client):
        result = domain.read_app_logs("web", 300)
    assert result.truncated and len(result.text) <= domain.MAX_READ_CHARS
    assert set(result.text.split("\n")) == {"x" * 99}


@pytest.mark.parametrize("lines", [0, 301])
def test_line_count_is_bounded(lines):
    with pytest.raises(ValueError, match="between 1 and 300"):
        domain.read_app_logs("web", lines)

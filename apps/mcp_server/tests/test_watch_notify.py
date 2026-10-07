"""Tests for the watcher notification email: recipient, content and the three outcomes."""

from __future__ import annotations

from types import SimpleNamespace

from src.capabilities.watchers.utils.notify import send_watcher_email
from src.capabilities.watchers.utils.spec import WatchSpec


def spec(**changes) -> WatchSpec:
    values = dict(kind="url", target="https://example.com/", expect="up", contains="", label="Blog", owner="alice", email="alice@x.io")
    return WatchSpec(**{**values, **changes})


def configured(tmp_path):
    path = tmp_path / "config_email.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_the_email_goes_only_to_the_owner(tmp_path):
    sent = []
    loader = lambda path: SimpleNamespace(marker="config")

    outcome = send_watcher_email(
        spec(), "w-1234abcd", "met", 7, config_path=configured(tmp_path), loader=loader,
        sender=lambda config, alias, subject, html, **kw: sent.append((config, alias, subject, html, kw)),
    )

    assert outcome == "sent"
    ((config, alias, subject, html, kw),) = sent
    assert config.marker == "config" and alias == "watch" and kw == {"to": ["alice@x.io"]}
    assert subject == "Blog is up"
    assert "https://example.com/" in html and "7" in html and "w-1234abcd" in html


def test_subjects_for_down_and_timeout(tmp_path):
    subjects = []
    send = lambda config, alias, subject, html, **kw: subjects.append(subject)
    path = configured(tmp_path)

    send_watcher_email(spec(expect="down"), "k", "met", 1, config_path=path, loader=lambda p: None, sender=send)
    send_watcher_email(spec(), "k", "timed_out", 9, config_path=path, loader=lambda p: None, sender=send)

    assert subjects == ["Blog is down", "Gave up watching Blog"]


def test_text_from_the_spec_is_escaped_in_the_body(tmp_path):
    bodies = []

    send_watcher_email(
        spec(label="<b>x</b>"), "k", "met", 1, config_path=configured(tmp_path), loader=lambda p: None,
        sender=lambda config, alias, subject, html, **kw: bodies.append(html),
    )

    assert "&lt;b&gt;x&lt;/b&gt;" in bodies[0] and "<b>x</b>" not in bodies[0]


def test_no_address_means_skipped_and_nothing_is_loaded(tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("must not be called")

    outcome = send_watcher_email(spec(email=""), "k", "met", 1, config_path=configured(tmp_path), loader=boom, sender=boom)

    assert outcome.startswith("skipped:") and "address" in outcome


def test_a_missing_config_is_skipped_without_loading_it(tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("loading would copy the .example file")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=tmp_path / "config_email.json", loader=boom, sender=boom)

    assert outcome == "skipped: email is not configured"


def test_an_invalid_config_is_skipped_with_the_reason(tmp_path):
    def bad(path):
        raise ValueError("password placeholder is empty")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=configured(tmp_path), loader=bad, sender=lambda *a, **k: None)

    assert outcome.startswith("skipped: email config is invalid") and "password placeholder" in outcome


def test_a_send_failure_is_reported_not_raised(tmp_path):
    def down(*args, **kwargs):
        raise OSError("connection refused")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=configured(tmp_path), loader=lambda p: None, sender=down)

    assert outcome.startswith("failed: OSError") and "connection refused" in outcome

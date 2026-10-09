"""Tests for the watcher notification email: recipient, content and the three outcomes."""

from __future__ import annotations

from src.capabilities.watchers.utils.notify import send_watcher_email
from src.capabilities.watchers.utils.spec import WatchSpec
from src.services.email_delivery import EmailUnavailable, EmailDeliveryError


def spec(**changes) -> WatchSpec:
    values = dict(kind="url", target="https://example.com/", expect="up", contains="", label="Blog", owner="alice", email="alice@x.io")
    return WatchSpec(**{**values, **changes})


def configured(tmp_path):
    path = tmp_path / "config_email.json"
    path.write_text("{}", encoding="utf-8")
    return path


def test_the_email_goes_only_to_the_owner(tmp_path):
    sent = []

    outcome = send_watcher_email(
        spec(), "w-1234abcd", "met", 7, config_path=configured(tmp_path),
        sender=lambda to, subject, text, **kw: sent.append((to, subject, text, kw)),
    )

    assert outcome == "sent"
    ((to, subject, text, kw),) = sent
    assert to == ["alice@x.io"] and kw["capability_alias"] == "watch" and kw["owner"] == "alice"
    html = kw["body_html"]
    assert subject == "Blog is up"
    assert "https://example.com/" in html and "7" in html and "w-1234abcd" in html


def test_subjects_for_down_and_timeout(tmp_path):
    subjects = []
    send = lambda to, subject, text, **kw: subjects.append(subject)
    path = configured(tmp_path)

    send_watcher_email(spec(expect="down"), "k", "met", 1, config_path=path, sender=send)
    send_watcher_email(spec(), "k", "timed_out", 9, config_path=path, sender=send)

    assert subjects == ["Blog is down", "Gave up watching Blog"]


def test_text_from_the_spec_is_escaped_in_the_body(tmp_path):
    bodies = []

    send_watcher_email(
        spec(label="<b>x</b>"), "k", "met", 1, config_path=configured(tmp_path),
        sender=lambda to, subject, text, **kw: bodies.append(kw["body_html"]),
    )

    assert "&lt;b&gt;x&lt;/b&gt;" in bodies[0] and "<b>x</b>" not in bodies[0]


def test_no_address_means_skipped_and_nothing_is_loaded(tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("must not be called")

    outcome = send_watcher_email(spec(email=""), "k", "met", 1, config_path=configured(tmp_path), sender=boom)

    assert outcome.startswith("skipped:") and "address" in outcome


def test_an_unavailable_email_capability_is_skipped(tmp_path):
    def boom(*args, **kwargs):
        raise EmailUnavailable("email capability is disabled")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=tmp_path / "config_email.json", sender=boom)

    assert outcome.startswith("skipped:") and "disabled" in outcome


def test_an_invalid_config_is_skipped_with_the_reason(tmp_path):
    def bad(*args, **kwargs):
        raise EmailUnavailable("email config is invalid")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=configured(tmp_path), sender=bad)

    assert outcome.startswith("skipped: email config is invalid")


def test_a_send_failure_is_reported_not_raised(tmp_path):
    def down(*args, **kwargs):
        raise EmailDeliveryError("Email delivery failed")

    outcome = send_watcher_email(spec(), "k", "met", 1, config_path=configured(tmp_path), sender=down)

    assert outcome.startswith("failed:")


def test_unexpected_error_does_not_leak_its_contents(tmp_path):
    def down(*args, **kwargs):
        raise OSError("private secret")
    outcome = send_watcher_email(spec(), "k", "met", 1, sender=down)
    assert outcome.startswith("failed:") and "private secret" not in outcome

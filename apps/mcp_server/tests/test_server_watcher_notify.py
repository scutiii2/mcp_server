"""Tests for the owner email helper used by ServerWatcher."""

from __future__ import annotations

from src.capabilities.server_manager.utils import notify
from src.services.email_delivery import EmailUnavailable


def test_sends_one_notification_to_the_owner_address():
    sent = []

    def sender(to, subject, body_text, **kwargs):
        sent.append((to, subject, body_text, kwargs))
        return "message-id"

    result = notify.send_owner_email("alice", "alice@x.io", "web stopped", "It stopped.", "<p>d</p>", sender=sender)

    assert result == "sent"
    ((to, subject, body_text, kwargs),) = sent
    assert to == ["alice@x.io"] and subject == "web stopped" and body_text is None
    assert kwargs["owner"] == "alice" and kwargs["capability_alias"] == "server"
    assert "web stopped" in kwargs["body_html"] and "It stopped." in kwargs["body_html"]


def test_no_address_means_skipped_without_calling_the_sender():
    def sender(*args, **kwargs):
        raise AssertionError("must not send")

    result = notify.send_owner_email("alice", "", "s", "m", "", sender=sender)

    assert result.startswith("skipped:")


def test_unavailable_email_is_skipped_with_the_reason():
    def sender(*args, **kwargs):
        raise EmailUnavailable("email capability is disabled")

    assert notify.send_owner_email("a", "a@x.io", "s", "m", "", sender=sender) == "skipped: email capability is disabled"


def test_any_other_error_is_reported_without_its_contents():
    def sender(*args, **kwargs):
        raise RuntimeError("smtp password hunter2")

    result = notify.send_owner_email("a", "a@x.io", "s", "m", "", sender=sender)

    assert result.startswith("failed:") and "hunter2" not in result

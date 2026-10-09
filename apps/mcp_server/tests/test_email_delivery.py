from __future__ import annotations

import dataclasses
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from src.services import capability_registry, email_delivery, email_audit
from src.config import settings


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    cfg = tmp_path / "config_email.json"
    cfg.write_text(json.dumps({"smtp_server": "smtp.example.com", "smtp_port": 587,
                              "from": "sender@example.com", "password": "private-password"}))
    test_settings = dataclasses.replace(settings, configs_dir=tmp_path, email_audit_path=tmp_path / "audit.db")
    monkeypatch.setattr(email_delivery, "settings", test_settings)
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})
    capability_registry.register_unloaded("email", "Email")
    capability_registry._REGISTRY["email"].enabled = True
    smtp = MagicMock()
    server = smtp.return_value.__enter__.return_value
    server.sendmail.return_value = {}
    monkeypatch.setattr("smtplib.SMTP", smtp)
    return cfg, test_settings.email_audit_path, smtp


def send(**kwargs):
    return email_delivery.deliver_email(["alice@example.com"], "Private subject", "Secret code ABC123", owner="alice", **kwargs)


def test_delivery_returns_id_and_audits_only_metadata(delivery, caplog):
    _, path, smtp = delivery
    message_id = send()
    assert message_id.startswith("<")
    rows = email_audit.read_audit(path, "alice", 20)
    assert len(rows) == 1
    assert rows[0]["message_id"] == message_id and rows[0]["outcome"] == "sent"
    assert rows[0]["recipient_count"] == 1
    persisted = path.read_bytes()
    for private in (b"ABC123", b"Private subject", b"alice@example.com", b"private-password"):
        assert private not in persisted
        assert private.decode() not in caplog.text
    assert email_audit.read_audit(path, "bob", 20) == []
    assert email_audit.read_audit(path, "", 20) == []
    assert smtp.call_count == 1


@pytest.mark.parametrize("registered", [True, False])
def test_disabled_or_unregistered_email_never_connects(delivery, registered):
    _, _, smtp = delivery
    if registered:
        capability_registry._REGISTRY["email"].enabled = False
    else:
        capability_registry._REGISTRY.clear()
    with pytest.raises(email_delivery.EmailUnavailable, match="disabled"):
        send()
    smtp.assert_not_called()


def test_missing_config_is_not_created(delivery):
    cfg, _, smtp = delivery
    cfg.unlink()
    with pytest.raises(email_delivery.EmailUnavailable, match="not configured"):
        send()
    assert not cfg.exists()
    smtp.assert_not_called()


def test_invalid_config_is_sanitized(delivery, caplog):
    cfg, _, smtp = delivery
    cfg.write_text('{"secret": "ABC123"}')
    with pytest.raises(email_delivery.EmailUnavailable, match="config is invalid") as error:
        send()
    assert "ABC123" not in str(error.value) + caplog.text
    smtp.assert_not_called()


def test_transport_error_is_sanitized_and_audited_without_retry(delivery, caplog):
    _, path, smtp = delivery
    smtp.side_effect = OSError("private-password ABC123")
    with pytest.raises(email_delivery.EmailDeliveryError) as error:
        send()
    assert "ABC123" not in str(error.value) + caplog.text
    assert smtp.call_count == 1
    assert email_audit.read_audit(path, "alice", 20)[0]["outcome"] == "failed"


def test_audit_failure_does_not_turn_accepted_email_into_failure(delivery, monkeypatch):
    monkeypatch.setattr(email_audit, "record_delivery", lambda *a, **k: (_ for _ in ()).throw(OSError("ABC123")))
    assert send().startswith("<")


def test_concurrent_audit_inserts_keep_all_records(delivery):
    _, path, _ = delivery
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: email_audit.record_delivery(path, "alice", "sent", 1, f"<{n}@example.com>"), range(12)))
    assert len(email_audit.read_audit(path, "alice", 20)) == 12

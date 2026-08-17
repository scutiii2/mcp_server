from __future__ import annotations

import dataclasses

from chat_app import errors
from chat_app.config import settings as base_settings


def test_report_returns_reference_and_logs_full_detail(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(errors, "settings", dataclasses.replace(base_settings, log_dir=tmp_path))
    boom = RuntimeError("connect failed: postgres://admin:hunter2@10.0.0.5:5432")

    message = errors.report(boom, context="doing a thing")

    assert "hunter2" not in message
    reference = message.rsplit("reference ", 1)[1].rstrip(".")
    assert reference in caplog.text
    assert "hunter2" in caplog.text


def test_report_writes_a_per_reference_file(monkeypatch, tmp_path):
    monkeypatch.setattr(errors, "settings", dataclasses.replace(base_settings, log_dir=tmp_path))
    boom = RuntimeError("connect failed: postgres://admin:hunter2@10.0.0.5:5432")

    message = errors.report(boom, context="doing a thing")

    reference = message.rsplit("reference ", 1)[1].rstrip(".")
    error_file = tmp_path / "errors" / f"{reference}.log"
    assert error_file.exists()
    content = error_file.read_text(encoding="utf-8")
    assert "hunter2" in content
    assert "doing a thing" in content
    assert "RuntimeError" in content

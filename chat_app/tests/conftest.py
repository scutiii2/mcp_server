from dataclasses import replace

import pytest
from flask import Flask

from src.models import db


@pytest.fixture(autouse=True)
def _isolated_tool_capabilities_cache(tmp_path, monkeypatch):
    """tool_capabilities.py persists mcp_server's capability data to disk
    (settings.capability_cache_path) and keeps a live copy in mutable
    module-level dicts - real state that must never point at this
    machine's actual cache file from a test, and must not leak between
    tests (module-level state otherwise survives for the whole pytest
    process). Every test gets its own throwaway cache path and starts
    from an empty map, regardless of what an earlier test cached."""
    from src.services import tool_capabilities

    monkeypatch.setattr(
        tool_capabilities, "settings",
        replace(tool_capabilities.settings, capability_cache_path=tmp_path / "capability_tool_cache.json"),
    )
    tool_capabilities._apply([])
    yield
    tool_capabilities._apply([])


@pytest.fixture
def app(tmp_path):
    application = Flask(__name__)
    db_path = tmp_path / "test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"

    db.init_app(application)
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()

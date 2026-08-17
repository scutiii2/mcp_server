from __future__ import annotations

import dataclasses

import pytest

from mcp_server import errors
from mcp_server.config import settings as base_settings


@pytest.fixture(autouse=True)
def log_dir(tmp_path, monkeypatch):
    """Points errors.report()'s per-error files at a throwaway directory.

    Without this, any test that triggers report() (e.g. approval_submit's
    failure branch) would write into the real, CWD-relative logs/
    directory as a side effect of running the test suite."""
    test_settings = dataclasses.replace(base_settings, log_dir=tmp_path / "logs")
    monkeypatch.setattr(errors, "settings", test_settings)
    return test_settings.log_dir

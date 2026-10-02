"""Shared fixtures. Later tasks add fixtures to this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings

TEST_TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that keep every file under tmp_path."""
    return Settings(
        store_dir=tmp_path / "store",
        log_dir=tmp_path / "logs",
        internal_api_token=TEST_TOKEN,
        signing_key=b"s" * 32,
    )

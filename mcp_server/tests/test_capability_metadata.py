"""Tests for infra/capability_metadata.py.

title_for()/command_id_for() are exercised against the real
capabilities/host_health and capabilities/otp packages (one with both
TITLE and COMMAND_ID set, one with only TITLE) rather than fixtures -
they're plain importable packages, and this is the exact contract a
real capability needs to satisfy. validate_command_ids() is tested
against synthetic names instead, since collisions are exactly the
scenario that must never occur among real capabilities.
"""

from __future__ import annotations

import pytest

from src.infra import capability_metadata


def test_title_for_reads_the_real_capabilitys_title():
    assert capability_metadata.title_for("host_health") == "Host Health"


def test_command_id_for_reads_the_real_capabilitys_command_id():
    assert capability_metadata.command_id_for("host_health") == "host"


def test_command_id_for_falls_back_to_the_real_id_when_unset():
    # otp/__init__.py sets TITLE but no COMMAND_ID.
    assert capability_metadata.command_id_for("otp") == "otp"


def test_title_for_falls_back_to_the_id_for_an_unimportable_capability():
    assert capability_metadata.title_for("no_such_capability") == "no_such_capability"


def test_command_id_for_falls_back_to_the_id_for_an_unimportable_capability():
    assert capability_metadata.command_id_for("no_such_capability") == "no_such_capability"


def test_validate_command_ids_passes_when_every_id_is_distinct():
    capability_metadata.validate_command_ids(["host_health", "otp", "crafty", "server_manager"])  # must not raise


def test_validate_command_ids_raises_on_a_collision(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(capability_metadata, "command_id_for", lambda name: "same")

    with pytest.raises(ValueError, match="same"):
        capability_metadata.validate_command_ids(["alpha", "beta"])

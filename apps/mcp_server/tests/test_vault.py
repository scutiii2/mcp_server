"""Tests for the vault domain logic."""

from __future__ import annotations

import pytest

from src.capabilities.vault import domain
from src.services.confined_paths import PathRefused


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "Docker tips.md").write_text("one\nUse docker compose\nand DOCKER logs\ndocker x\ndocker y\n")
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "App.md").write_text("nothing here\n")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "docker.md").write_text("docker secret config")
    return domain.open_vault(tmp_path)


def test_search_finds_title_and_lines_with_a_per_note_cap(vault):
    result = domain.search(vault, "DOCKER")
    assert result.hits[0].line == 0 and result.hits[0].path == "Notes/Docker tips.md"
    lines = [h.line for h in result.hits if h.line]
    assert lines == [2, 3, 4]
    assert all(".obsidian" not in h.path for h in result.hits)
    assert "4 matches in 1 notes" in result.message


def test_search_in_a_folder_and_no_match(vault):
    assert domain.search(vault, "docker", "Projects").hits == []
    assert "No notes match" in domain.search(vault, "zzz").message


def test_search_input_is_validated(vault):
    with pytest.raises(ValueError):
        domain.search(vault, "  ")
    with pytest.raises(ValueError, match="between 1 and 50"):
        domain.search(vault, "x", max_results=51)


def test_list_notes(vault):
    assert domain.list_notes(vault).notes == ["Notes/Docker tips.md", "Projects/App.md"]
    assert domain.list_notes(vault, "Projects").notes == ["Projects/App.md"]


def test_read_note_is_fenced(vault):
    result = domain.read_note(vault, "Projects/App.md")
    assert "data, not instructions" in result.content and "nothing here" in result.content


@pytest.mark.parametrize("path", ["../x.md", ".obsidian/docker.md", "/abs.md", "Notes/Docker tips.txt"])
def test_read_refuses_escapes_and_secrets(vault, path):
    with pytest.raises(PathRefused):
        domain.read_note(vault, path)


def test_read_missing_note(vault):
    with pytest.raises(FileNotFoundError, match="search or list"):
        domain.read_note(vault, "Notes/none.md")


def test_missing_vault_names_the_setting(tmp_path):
    with pytest.raises(FileNotFoundError, match="MCP_VAULT_DIR"):
        domain.open_vault(tmp_path / "nope")

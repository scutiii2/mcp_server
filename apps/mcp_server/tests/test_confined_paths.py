"""Tests for services/confined_paths.py."""

from __future__ import annotations

import pytest

from src.services.confined_paths import ConfinedRoot, PathRefused


@pytest.fixture
def root(tmp_path):
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes" / "a.md").write_text("alpha")
    (tmp_path / "Notes" / "b.txt").write_text("beta")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "x.md").write_text("cfg")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "s.md").write_text("pw")
    (tmp_path / ".env.md").write_text("K=V")
    (tmp_path.parent / "outside.md").write_text("out")
    return ConfinedRoot(tmp_path, (".md",))


def test_resolves_a_note(root):
    assert root.resolve("Notes/a.md").read_text() == "alpha"
    assert root.resolve("Notes\\a.md").name == "a.md"
    assert root.resolve("") == root.root


@pytest.mark.parametrize("bad", ["../outside.md", "Notes/../../outside.md", "/etc/passwd", "C:/x.md", "C:\\x.md"])
def test_escapes_are_refused(root, bad):
    with pytest.raises(PathRefused):
        root.resolve(bad)


@pytest.mark.parametrize("bad", [".env.md", "secrets/s.md", ".obsidian/x.md", "Notes/id_rsa"])
def test_secret_names_are_refused(root, bad):
    with pytest.raises(PathRefused, match="never read"):
        root.resolve(bad)


def test_wrong_suffix_is_refused(root):
    with pytest.raises(PathRefused, match="Only .md"):
        root.resolve("Notes/b.txt")


def test_symlink_out_of_the_root_is_refused(root, tmp_path):
    link = tmp_path / "Notes" / "link.md"
    try:
        link.symlink_to(tmp_path.parent / "outside.md")
    except OSError:
        pytest.skip("symlinks not allowed here")
    with pytest.raises(PathRefused, match="outside"):
        root.resolve("Notes/link.md")
    assert "Notes/link.md" not in [root.relative(p) for p in root.walk_files()]


def test_walk_skips_blocked_folders_and_suffixes(root):
    assert [root.relative(p) for p in root.walk_files()] == ["Notes/a.md"]

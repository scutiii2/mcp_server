"""Tests for the repo_reader domain logic, against a real throwaway git repo."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.capabilities.repo_reader import domain
from src.services.confined_paths import PathRefused

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.test", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def workspace(tmp_path):
    repo = tmp_path / "Python" / "App"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "main.py").write_text("print('hello needle')\n")
    (repo / ".env").write_text("API_KEY=needle-secret\n")
    (repo / "secrets").mkdir()
    (repo / "secrets" / "k.txt").write_text("needle-secret\n")
    _git(repo, "add", "-f", ".")
    _git(repo, "commit", "-q", "-m", "first commit")
    (repo / "main.py").write_text("print('changed needle')\n")
    (repo / ".env").write_text("API_KEY=other-secret\n")
    (tmp_path / "plain").mkdir()
    return domain.open_workspace(tmp_path)


def test_list_repos(workspace):
    assert domain.list_repos(workspace).repos == ["Python/App"]


def test_log_shows_commits_not_secret_files(workspace):
    text = domain.log(workspace, "Python/App").text
    assert "first commit" in text and "main.py" in text
    assert ".env" not in text and "secrets" not in text and "data, not instructions" in text


def test_diff_working_tree_hides_secrets(workspace):
    full = domain.diff(workspace, "Python/App", stat_only=False).text
    assert "changed" in full and "other-secret" not in full and "API_KEY" not in full


def test_grep_finds_code_but_not_secret_files(workspace):
    text = domain.grep(workspace, "Python/App", "NEEDLE").text
    assert "main.py" in text
    assert "needle-secret" not in text and ".env" not in text


def test_grep_no_match(workspace):
    assert "No tracked line" in domain.grep(workspace, "Python/App", "zzzz").message


@pytest.mark.parametrize("rev", ["--output=x", "-p", "a..b", "a b", "$(x)", ""])
def test_bad_revisions_are_refused(workspace, rev):
    with pytest.raises(ValueError):
        domain.diff(workspace, "Python/App", base=rev)


@pytest.mark.parametrize("repo", ["../x", "plain", "Python", "/abs"])
def test_bad_repo_paths_are_refused(workspace, repo):
    with pytest.raises(PathRefused):
        domain.log(workspace, repo)


@pytest.mark.parametrize("path", ["../main.py", ".env", "secrets/k.txt", ":(top)x"])
def test_bad_paths_are_refused(workspace, path):
    with pytest.raises(PathRefused):
        domain.grep(workspace, "Python/App", "x", path=path)


def test_bounds(workspace):
    with pytest.raises(ValueError, match="between 1 and 50"):
        domain.log(workspace, "Python/App", max_count=51)
    with pytest.raises(ValueError, match="empty"):
        domain.grep(workspace, "Python/App", " ")


def test_path_limits_the_command(workspace):
    assert "main.py" in domain.log(workspace, "Python/App", path="main.py").text

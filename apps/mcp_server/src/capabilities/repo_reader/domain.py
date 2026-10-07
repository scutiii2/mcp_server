"""Read-only git over the projects in the workspace.

Only fixed git subcommands run, with no shell. A caller's text goes in as a
pattern, a revision or a path, never as an option: revisions are checked
against a strict character set, paths go after `--`, patterns after `-e`.
Secret files are left out of every command with pathspec excludes, and the
repo path itself goes through `ConfinedRoot`.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from src.capabilities.repo_reader.contract import RepoListResult, RepoTextResult
from src.services import untrusted
from src.services.confined_paths import ConfinedRoot, PathRefused, is_blocked_name

GIT_TIMEOUT_SECONDS = 20
MAX_OUTPUT_BYTES = 24_000
MAX_COMMITS = 50
MAX_MATCHES = 100
MAX_REPO_DEPTH = 3
_REV = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,100}$")

# Files a command must never show, whatever repo or path it is asked about.
_EXCLUDES = tuple(
    f":(exclude,glob)**/{pattern}"
    for pattern in (".env*", "secrets/**", ".secrets/**", "*.key", "*.pem", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*")
)


def open_workspace(workspace_dir: Path) -> ConfinedRoot:
    if not workspace_dir.is_dir():
        raise FileNotFoundError(f"No workspace folder at {workspace_dir.resolve()}. Set MCP_WORKSPACE_DIR in .env.")
    return ConfinedRoot(workspace_dir)


def list_repos(workspace: ConfinedRoot) -> RepoListResult:
    repos: list[str] = []
    base = len(workspace.root.parts)
    for folder, dirs, _ in os.walk(workspace.root):
        depth = len(Path(folder).parts) - base
        if ".git" in dirs or (Path(folder) / ".git").is_file():
            repos.append(Path(folder).relative_to(workspace.root).as_posix() or ".")
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not is_blocked_name(d)) if depth < MAX_REPO_DEPTH else []
    message = f"{len(repos)} repos." if repos else "No git repos found in the workspace."
    return RepoListResult(repos=repos, message=message)


def log(workspace: ConfinedRoot, repo: str, max_count: int = 20, path: str = "", author: str = "", since: str = "") -> RepoTextResult:
    _bounded("max_count", max_count, MAX_COMMITS)
    args = ["log", f"--max-count={max_count}", "--date=short", "--pretty=format:%h %ad %an  %s", "--stat=100"]
    if author.strip():
        args.append(f"--author={_clean_option(author)}")
    if since.strip():
        args.append(f"--since={_clean_option(since)}")
    root = _repo(workspace, repo)
    args += ["--", *_pathspec(root, path)]
    return _run(root, repo, args, f"Newest {max_count} commits of {repo}.")


def diff(workspace: ConfinedRoot, repo: str, base: str = "HEAD", target: str = "", path: str = "", stat_only: bool = True) -> RepoTextResult:
    args = ["diff", "--stat=100" if stat_only else "--unified=3", _rev(base)]
    if target.strip():
        args.append(_rev(target))
    root = _repo(workspace, repo)
    args += ["--", *_pathspec(root, path)]
    what = f"{base}..{target}" if target.strip() else f"{base} against the working tree"
    return _run(root, repo, args, f"{'Changed files' if stat_only else 'Diff'} for {what} in {repo}.")


def grep(workspace: ConfinedRoot, repo: str, pattern: str, path: str = "", max_matches: int = 50) -> RepoTextResult:
    if not pattern.strip():
        raise ValueError("pattern must not be empty")
    _bounded("max_matches", max_matches, MAX_MATCHES)
    root = _repo(workspace, repo)
    args = ["grep", "-n", "-I", "-i", "-F", f"--max-count={max_matches}", "-e", pattern, "--", *_pathspec(root, path)]
    return _run(root, repo, args, f"Tracked lines in {repo} holding {pattern!r}.", empty=f"No tracked line in {repo} holds {pattern!r}.")


def _repo(workspace: ConfinedRoot, repo: str) -> Path:
    root = workspace.resolve(repo)
    if not (root / ".git").exists():
        raise PathRefused(f"{repo!r} is not a git repo. Use the repo list to find the exact path.")
    return root


def _pathspec(root: Path, path: str) -> list[str]:
    """The pathspecs for a command: the caller's path (checked inside the repo) plus the secret excludes."""
    if path.strip().startswith(":"):
        raise PathRefused("A path may not start with ':'.")
    inside = ConfinedRoot(root)
    spec = inside.relative(inside.resolve(path)) if path.strip() else ""
    return [spec or ".", *_EXCLUDES]


def _rev(value: str) -> str:
    value = value.strip()
    if not _REV.match(value) or value.startswith("-") or ".." in value:
        raise ValueError(f"{value!r} is not a plain branch, tag or commit name.")
    return value


def _clean_option(value: str) -> str:
    value = value.strip()
    if len(value) > 80 or any(ord(char) < 32 for char in value):
        raise ValueError("A filter value must be short plain text.")
    return value


def _bounded(name: str, value: int, limit: int) -> None:
    if not 1 <= value <= limit:
        raise ValueError(f"{name} must be between 1 and {limit}, not {value}")


def _run(root: Path, repo: str, args: list[str], message: str, empty: str = "") -> RepoTextResult:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(
            ["git", "--no-pager", "-c", "core.quotepath=off", "-C", str(root), *args],
            capture_output=True, timeout=GIT_TIMEOUT_SECONDS, env=env, check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("git is not installed or not on PATH for this server.") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"git took longer than {GIT_TIMEOUT_SECONDS}s and was stopped.") from error
    if done.returncode not in (0, 1):  # git grep exits 1 for "no match"
        reason = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(f"git failed: {reason[0] if reason else 'exit ' + str(done.returncode)}")
    output = done.stdout.decode("utf-8", errors="replace")
    if not output.strip():
        return RepoTextResult(repo=repo, text="", message=empty or f"Nothing to show for {repo}.")
    text = untrusted.fenced_and_capped(output, source=f"git in {repo}", max_bytes=MAX_OUTPUT_BYTES)
    return RepoTextResult(repo=repo, text=text, message=message)

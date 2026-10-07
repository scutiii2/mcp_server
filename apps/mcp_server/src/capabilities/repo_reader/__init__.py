"""Repo reader: read-only git history, diffs and code search over the workspace projects."""

from src.services import capability_meta

META = capability_meta.register(folder="repo_reader", id="repo", label="Repo Reader")

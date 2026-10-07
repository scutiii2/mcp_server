"""Vault: search and read the Obsidian vault, read-only."""

from src.services import capability_meta

META = capability_meta.register(folder="vault", id="vault", label="Vault")

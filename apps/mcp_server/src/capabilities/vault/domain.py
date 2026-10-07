"""Search and read the Obsidian vault. Read-only, markdown only.

Every path goes through `ConfinedRoot`, so a caller cannot leave the vault
or reach `.obsidian`, `.git` or anything that looks like a secret.
"""

from __future__ import annotations

from pathlib import Path

from src.capabilities.vault.contract import NoteHit, NoteListResult, NoteResult, VaultSearchResult
from src.services import untrusted
from src.services.confined_paths import ConfinedRoot, PathRefused

MAX_RESULTS = 50
MAX_PER_NOTE = 3
MAX_LIST = 300
MAX_NOTE_BYTES = 24_000
MAX_SCAN_BYTES = 400_000
MAX_LINE_CHARS = 300


def open_vault(vault_dir: Path) -> ConfinedRoot:
    if not vault_dir.is_dir():
        raise FileNotFoundError(f"No vault folder at {vault_dir.resolve()}. Set MCP_VAULT_DIR in .env.")
    return ConfinedRoot(vault_dir, (".md",))


def search(vault: ConfinedRoot, query: str, folder: str = "", max_results: int = 15) -> VaultSearchResult:
    needle = query.strip().lower()
    if not needle:
        raise ValueError("query must not be empty")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}, not {max_results}")
    start = _folder(vault, folder)
    hits: list[NoteHit] = []
    for path in vault.walk_files(start):
        if len(hits) >= max_results:
            break
        rel = vault.relative(path)
        if needle in path.stem.lower():
            hits.append(NoteHit(path=rel, line=0, text=path.stem))
        found = 0
        text = path.read_bytes()[:MAX_SCAN_BYTES].decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append(NoteHit(path=rel, line=number, text=_clip(line)))
                found += 1
                if found >= MAX_PER_NOTE or len(hits) >= max_results:
                    break
    notes = len({hit.path for hit in hits})
    message = f"{len(hits)} matches in {notes} notes for {query!r}." if hits else f"No notes match {query!r}."
    return VaultSearchResult(query=query, hits=hits, message=message)


def list_notes(vault: ConfinedRoot, folder: str = "") -> NoteListResult:
    start = _folder(vault, folder)
    notes = [vault.relative(path) for path in vault.walk_files(start)]
    shown = notes[:MAX_LIST]
    note = f" Showing the first {MAX_LIST}; give a narrower folder." if len(notes) > MAX_LIST else ""
    return NoteListResult(folder=folder.strip(), notes=shown, message=f"{len(notes)} notes.{note}")


def read_note(vault: ConfinedRoot, path: str) -> NoteResult:
    if not path.strip().lower().endswith(".md"):
        raise PathRefused("Only .md notes are read here.")
    target = vault.resolve(path)
    if not target.is_file():
        raise FileNotFoundError(f"No note at {path!r}. Use the vault search or list to find the exact path.")
    text = target.read_text(encoding="utf-8", errors="replace")
    rel = vault.relative(target)
    content = untrusted.fenced_and_capped(text, source=f"vault note {rel}", max_bytes=MAX_NOTE_BYTES)
    return NoteResult(path=rel, content=content, message=f"Read {rel} ({len(text)} characters).")


def _folder(vault: ConfinedRoot, folder: str) -> Path:
    target = vault.resolve(folder)
    if not target.is_dir():
        raise PathRefused(f"{folder!r} is not a folder in the vault.")
    return target


def _clip(line: str) -> str:
    line = line.strip()
    return line if len(line) <= MAX_LINE_CHARS else line[: MAX_LINE_CHARS - 3] + "..."

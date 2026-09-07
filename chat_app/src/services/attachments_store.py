"""Per-chat file attachment storage: one folder per chat_id under a
configured attachments_dir, one file per attachment. Same conventions
as chats_store.py: plain filesystem/pathlib, no ORM, functions take
already-resolved paths/values rather than reading config themselves.

Only UTF-8-decodable text is accepted - save_attachment rejects
anything else, and there is deliberately no way to store binary
content through this module (see the design spec's Non-goals: no
image/vision support).
"""

from __future__ import annotations

import shutil
from pathlib import Path


class AttachmentError(Exception):
    """A user-facing problem with an attachment - too big, not UTF-8
    text, or an unsafe filename. Its message is safe to show verbatim."""


def _safe_name(filename: str) -> str:
    name = (filename or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise AttachmentError(f"Invalid filename: {filename!r}")
    return name


def save_attachment(
    attachments_dir: Path, chat_id: str, filename: str, data: bytes, max_file_size_mb: float
) -> dict:
    safe_name = _safe_name(filename)
    max_bytes = int(max_file_size_mb * 1024 * 1024)
    if len(data) > max_bytes:
        raise AttachmentError(f"{filename!r} is too large - the limit is {max_file_size_mb}MB.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AttachmentError(f"{filename!r} isn't a text file (must be UTF-8-decodable).") from None

    chat_dir = Path(attachments_dir) / chat_id
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / safe_name).write_text(text, encoding="utf-8")
    return {"filename": safe_name, "size": len(data)}


def list_attachments(attachments_dir: Path, chat_id: str) -> list[dict]:
    chat_dir = Path(attachments_dir) / chat_id
    if not chat_dir.exists():
        return []
    entries = [{"filename": p.name, "size": p.stat().st_size} for p in chat_dir.iterdir() if p.is_file()]
    return sorted(entries, key=lambda entry: entry["filename"])


def read_attachment_text(attachments_dir: Path, chat_id: str, filename: str) -> str | None:
    try:
        safe_name = _safe_name(filename)
    except AttachmentError:
        return None
    path = Path(attachments_dir) / chat_id / safe_name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def delete_attachment(attachments_dir: Path, chat_id: str, filename: str) -> bool:
    try:
        safe_name = _safe_name(filename)
    except AttachmentError:
        return False
    path = Path(attachments_dir) / chat_id / safe_name
    if not path.is_file():
        return False
    path.unlink()
    return True


def delete_chat_attachments(attachments_dir: Path, chat_id: str) -> None:
    chat_dir = Path(attachments_dir) / chat_id
    if chat_dir.exists():
        shutil.rmtree(chat_dir)

"""Per-chat technical trace: one JSON line per turn, appended to
logs/chats/<user>/<chat_id>.jsonl.

Separate from chats/store.py's chats.db: that store holds the display
transcript the UI resumes a conversation from (question/answer text
only, plus just enough metadata - see routes.py's assistant_entry - to
show a compact "12.3s · 842 tokens · model · 3 recursive rounds" line).
This holds the full process behind each turn - which provider/model
answered, what tools it called, with what arguments, what came back,
and (for a recursive_chain model) each self-review round's own answer,
not just the final count - for debugging or auditing what actually
happened, not for rendering in the app.

Deliberately not wired to raise into the request: a write failure here
must not break the chat answer itself, same reasoning as chats_store's
own save - see routes.py's call site.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from chat_app.config import settings
from chat_app.services.llm.base import RecursiveRoundRecord, ToolCallRecord


# Usernames are self-registered with no charset restriction (see
# auth/routes.py) and this is the first place one becomes a filesystem
# path segment rather than a SQL column value - unlike anything not in
# this set becomes "_", so a username like "../../etc" can't escape
# logs/chats/.
_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _safe_username(username: str) -> str:
    return _UNSAFE_PATH_CHARS.sub("_", username) or "unknown"


def record_turn(
    username: str,
    chat_id: str,
    *,
    question: str,
    response: str,
    provider_id: str,
    model: str | None,
    tool_calls: list[ToolCallRecord],
    recursive_rounds: list[RecursiveRoundRecord],
    total_tokens: int | None,
    elapsed_seconds: float | None = None,
) -> None:
    chat_dir = settings.log_dir / "chats" / _safe_username(username)
    chat_dir.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "provider_id": provider_id,
        "model": model,
        "tool_calls": [asdict(call) for call in tool_calls],
        "recursive_rounds": [asdict(round_) for round_ in recursive_rounds],
        "response": response,
        "total_tokens": total_tokens,
        "elapsed_seconds": elapsed_seconds,
    }
    with (chat_dir / f"{chat_id}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")

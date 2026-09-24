"""One-time backfill of agent/model/chat id onto usage rows recorded before
usage_limits.token_usage had those columns.

Each old row (agent IS NULL) is matched to the assistant message in
chats.db that has the same user, the same total_tokens and a sent_at within
a couple of minutes of the row's timestamp (the row is written just before
the message is saved). Every message is used at most once, closest first.
Input/output tokens were never stored, so they stay empty. Rows with no
match (deleted or summarized-away chats) are left as they are.

Run from chat_app/ (dry run by default):

    python -m src.services.usage_backfill
    python -m src.services.usage_backfill --apply

--apply copies usage.db to usage.db.bak-<timestamp> first.

Rows that match no message stay "unknown". If you know they all came from one
agent, --default-agent (and optionally --default-model) labels them; use it
only when that is really true:

    python -m src.services.usage_backfill --apply --default-agent anthropic
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.services import usage_limits

MAX_GAP_SECONDS = 120


def _assistant_messages(chats_db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(chats_db_path))
    try:
        rows = conn.execute("SELECT id, username, messages FROM chats").fetchall()
    finally:
        conn.close()
    found = []
    for chat_id, username, raw in rows:
        try:
            messages = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for message in messages:
            if message.get("role") != "assistant" or not message.get("provider_id"):
                continue
            tokens, sent_at = message.get("total_tokens"), message.get("sent_at")
            if not isinstance(tokens, int) or not sent_at:
                continue
            try:
                sent = datetime.fromisoformat(sent_at)
            except ValueError:
                continue
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            found.append({
                "username": username, "chat_id": chat_id, "tokens": tokens, "sent": sent,
                "agent": message["provider_id"], "model": message.get("model") or None,
            })
    return found


def backfill(
    usage_db_path: Path,
    chats_db_path: Path,
    apply: bool = False,
    default_agent: str | None = None,
    default_model: str | None = None,
) -> dict:
    """Returns {"candidates": rows without an agent, "matched": rows that
    found a message, "defaulted": unmatched rows labeled with default_agent}.
    With apply=True the changes are written."""
    messages = _assistant_messages(chats_db_path)
    conn = usage_limits._connect(usage_db_path)  # also adds any missing columns
    try:
        rows = conn.execute(
            "SELECT rowid, username, ts, tokens FROM token_usage WHERE agent IS NULL ORDER BY ts"
        ).fetchall()
        used: set[int] = set()
        updates = []
        for rowid, username, ts, tokens in rows:
            row_time = datetime.fromisoformat(ts)
            if row_time.tzinfo is None:
                row_time = row_time.replace(tzinfo=timezone.utc)
            best, best_gap = None, MAX_GAP_SECONDS + 1
            for index, message in enumerate(messages):
                if index in used or message["username"] != username or message["tokens"] != tokens:
                    continue
                gap = abs((message["sent"] - row_time).total_seconds())
                if gap < best_gap:
                    best, best_gap = index, gap
            if best is None:
                continue
            used.add(best)
            message = messages[best]
            updates.append((message["agent"], message["model"], message["chat_id"], rowid))
        if apply and updates:
            conn.executemany(
                "UPDATE token_usage SET agent = ?, model = ?, chat_id = ? WHERE rowid = ?", updates
            )
        defaulted = 0
        if default_agent:
            matched_ids = {update[3] for update in updates}
            unmatched = [row[0] for row in rows if row[0] not in matched_ids]
            defaulted = len(unmatched)
            if apply and unmatched:
                conn.executemany(
                    "UPDATE token_usage SET agent = ?, model = ? WHERE rowid = ?",
                    [(default_agent, default_model, rowid) for rowid in unmatched],
                )
        if apply:
            conn.commit()
        return {"candidates": len(rows), "matched": len(updates), "defaulted": defaulted}
    finally:
        conn.close()


def main() -> None:
    from src.services.llm.settings import settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the matches (default is a dry run)")
    parser.add_argument("--default-agent", help="label rows that match no message with this agent id")
    parser.add_argument("--default-model", help="model to record with --default-agent")
    args = parser.parse_args()

    if args.apply:
        backup = settings.usage_db_path.with_name(
            f"{settings.usage_db_path.name}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copyfile(settings.usage_db_path, backup)
        print(f"Backed up to {backup}")
    result = backfill(
        settings.usage_db_path, settings.chats_db_path, apply=args.apply,
        default_agent=args.default_agent, default_model=args.default_model,
    )
    verb = "Updated" if args.apply else "Would update"
    print(f"{verb} {result['matched']} of {result['candidates']} rows without an agent from chat messages.")
    if args.default_agent:
        print(f"{verb} {result['defaulted']} more with the default agent {args.default_agent!r}.")


if __name__ == "__main__":
    main()

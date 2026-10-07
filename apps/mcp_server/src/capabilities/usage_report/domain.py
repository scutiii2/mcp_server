"""Add up ai_agent's usage log.

ai_agent appends one JSON row per answer to `<usage_dir>/YYYY-MM-DD.<agent id>.jsonl`.
The date in the file name picks the files to read, so a long history costs
nothing for a short report. Read-only; a bad line is counted, never fatal.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from src.capabilities.usage_report.contract import UsageRow, UsageSummaryResult

MAX_DAYS = 90
GROUPS = ("agent", "model", "day")


def summarize(usage_dir: Path, days: int = 7, group_by: str = "agent", today: date | None = None) -> UsageSummaryResult:
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}, not {days}")
    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {', '.join(GROUPS)}, not {group_by!r}")
    if not usage_dir.is_dir():
        raise FileNotFoundError(f"No usage log folder at {usage_dir}. Set MCP_USAGE_DIR in .env to ai_agent's data/usage.")
    first = (today or date.today()) - timedelta(days=days - 1)
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    skipped = 0
    for path in sorted(usage_dir.glob("*.jsonl")):
        day = _file_date(path)
        if day is None or day < first:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = {"agent": row["agent_id"], "model": row["model"], "day": day.isoformat()}[group_by]
                bucket = totals[str(key)]
                bucket[0] += 1
                bucket[1] += int(row.get("input_tokens") or 0)
                bucket[2] += int(row.get("output_tokens") or 0)
            except (ValueError, KeyError, TypeError):
                skipped += 1
    rows = [UsageRow(key=key, requests=v[0], input_tokens=v[1], output_tokens=v[2], total_tokens=v[1] + v[2]) for key, v in totals.items()]
    rows.sort(key=(lambda r: r.key) if group_by == "day" else (lambda r: -r.total_tokens))
    requests = sum(r.requests for r in rows)
    total = sum(r.total_tokens for r in rows)
    message = f"{requests} answers, {total} tokens in the last {days} days, by {group_by}."
    return UsageSummaryResult(
        days=days, group_by=group_by, rows=rows, requests=requests, total_tokens=total, skipped_lines=skipped, message=message
    )


def _file_date(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.name[:10])
    except ValueError:
        return None

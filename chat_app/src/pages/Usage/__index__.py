from datetime import date, datetime, timedelta

from flask import Blueprint, Response, render_template, request
from flask_login import current_user

from src.services import usage_limits
from src.services.authz import has_permission, register_permission, require_permission
from src.services.llm.settings import settings

blueprint = Blueprint(
    "usage", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = "chat.access"
PAGE_DESCRIPTION = "Track your AI token usage by month, agent and day."

# Holding this lets an account open another user's tracker (?user=...).
register_permission("usage.view_all")

_RANGES = (
    ("month", "This month"),
    ("7d", "7 days"),
    ("30d", "30 days"),
    ("12m", "12 months"),
)
_RANGE_KEYS = {key for key, _ in _RANGES}
_HEATMAP_LEVELS = 4


def _compact(tokens: int) -> str:
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if tokens >= size:
            return f"{tokens / size:.1f}".rstrip("0").rstrip(".") + suffix
    return str(tokens)


def _hour_label(hour: int | None) -> str:
    if hour is None:
        return "-"
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def _target_user() -> str:
    """The user whose usage is shown: the requester, unless they may see
    everyone's and asked for someone else (?user=...)."""
    requested = (request.args.get("user") or "").strip()
    if requested and requested != current_user.username and has_permission(current_user, "usage.view_all"):
        return requested
    return current_user.username


def _range_key() -> str:
    key = request.args.get("range", "month")
    return key if key in _RANGE_KEYS else "month"


def _favorite_label(report: dict) -> str:
    favorite = report["favorite"]
    if not favorite:
        return "-"
    return f"{favorite['agent']} {favorite['model']}".strip()


def _heatmap(daily: dict[str, int]) -> dict:
    """Weeks (Sunday first) covering the last 12 months, each day with a
    0..4 intensity level relative to the busiest day."""
    today = date.today()
    first = usage_limits.range_start("12m").date()
    first -= timedelta(days=(first.weekday() + 1) % 7)
    peak = max(daily.values(), default=0)
    weeks = []
    day = first
    while day <= today:
        column = []
        for _ in range(7):
            tokens = daily.get(day.isoformat(), 0)
            level = 0
            if tokens and peak:
                level = max(1, -(-tokens * _HEATMAP_LEVELS // peak))
            column.append({
                "date": day.isoformat(),
                "tokens": tokens,
                "level": level if day <= today else None,
            })
            day += timedelta(days=1)
        weeks.append(column)
    return {"weeks": weeks}


@blueprint.route("/")
@require_permission("chat.access")
def index():
    username = _target_user()
    range_key = _range_key()
    can_view_all = has_permission(current_user, "usage.view_all")
    report = usage_limits.usage_report(settings.usage_db_path, username, range_key)
    year = usage_limits.usage_report(settings.usage_db_path, username, "12m")
    return render_template(
        "usage.html",
        report=report,
        heatmap=_heatmap(year["daily"]),
        ranges=_RANGES,
        range_key=range_key,
        username=username,
        users=usage_limits.usage_users(settings.usage_db_path) if can_view_all else [],
        can_view_all=can_view_all,
        compact=_compact,
        peak_hour=_hour_label(report["peak_hour"]),
        favorite=_favorite_label(report),
    )


@blueprint.route("/export.md")
@require_permission("chat.access")
def export_markdown():
    username = _target_user()
    range_key = _range_key()
    report = usage_limits.usage_report(settings.usage_db_path, username, range_key)
    label = dict(_RANGES)[range_key]
    lines = [
        f"# Token usage - {username}",
        "",
        f"Range: {label} (since {report['since'][:10]}). Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total tokens | {report['total_tokens']:,} |",
        f"| Input tokens | {report['input_tokens']:,} |",
        f"| Output tokens | {report['output_tokens']:,} |",
        f"| Chats | {report['chats']} |",
        f"| Turns | {report['turns']} |",
        f"| Active days | {report['active_days']} |",
        f"| Peak hour | {_hour_label(report['peak_hour'])} |",
        f"| Favorite agent | {_favorite_label(report)} |",
        "",
        "## By agent",
        "",
        "| Agent | Model | Tokens |",
        "|---|---|---|",
    ]
    lines += [f"| {a['agent']} | {a['model'] or '-'} | {a['tokens']:,} |" for a in report["by_agent"]]
    if not report["by_agent"]:
        lines.append("| - | - | 0 |")
    lines += ["", "## By day", "", "| Date | Tokens |", "|---|---|"]
    lines += [f"| {day} | {tokens:,} |" for day, tokens in sorted(report["daily"].items())]
    if not report["daily"]:
        lines.append("| - | 0 |")
    filename = f"usage-{username}-{range_key}-{date.today().isoformat()}.md"
    return Response(
        "\n".join(lines) + "\n",
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

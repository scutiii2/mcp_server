# pages/Usage/

Token usage tracker. URL prefix: `/usage`. Reached from the "Usage" panel in
the Chat sidebar ("Open usage tracker") or from the nav.

## Routes

| Route | Purpose |
|---|---|
| `GET /usage/?range=month\|7d\|30d\|12m&user=<name>` | Stat cards (chats, turns, total tokens, active days, peak hour, favorite agent), a 12-month day-by-day heatmap and a per-agent table |
| `GET /usage/export.md?range=...&user=...` | Same figures as a Markdown download |

`range=month` is the current calendar month (default). `user` is honored only
for accounts holding `usage.view_all`; everyone else always sees their own usage.

## Permissions

- `chat.access` — see your own usage (`PAGE_PERMISSION`).
- `usage.view_all` — pick another user's usage (a user picker appears).

Grant `usage.view_all` to a role from the Admin page.

## Data

Read from `usage.db` (`token_usage`, written by `services/usage_limits.py`).
One row per agent per turn (delegated agents get their own rows; rows of one
turn share a timestamp). The page shows the last 12 months; older rows stay in
the database and are never deleted. Rows recorded before input/output tracking
existed have no agent/model and show as `unknown`. Dates and the peak hour use
the server's local time zone.

## Templates

`usage.html`, `style.css`. No JavaScript: ranges, the user picker and the
export are plain links/forms.

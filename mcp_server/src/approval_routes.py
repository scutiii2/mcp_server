"""HTTP routes where a human approves a gated capability.

Mounted onto the Starlette app that ``mcp.streamable_http_app()`` returns
(see ``run.py``), and deliberately **not** exposed as ``@mcp.tool()``.
That distinction is the entire security property: a tool is something the
model can invoke by itself, so an approval-executing tool would let any
chat session - or any prompt injection reaching one - approve its own
request. Only something outside the MCP surface can be a real gate.

**GET renders, POST executes.** The GET handler has no side effects at
all, because links in email get fetched by things that are not the
recipient: corporate mail scanners prefetch URLs to check for malware,
chat clients unfurl them into previews, and some proxies warm them. If
opening the link performed the action, any of those would silently
approve a request before a human ever saw it. So GET shows the details
and asks; only the POST from pressing the button does anything.

The token is the whole authorization (see ``infra/approvals.py``), and
it's in the URL path so the emailed link works in one click. Two costs
that come with that: it lands in web-server access logs, and it would go
out in a ``Referer`` header if this page linked anywhere external - which
is why it doesn't, and why the pages here load nothing from a CDN.
"""

from __future__ import annotations

import html
import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse

from src.config import settings
from src.errors import report
from src.infra import approvals, pending_requests


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, sans-serif; line-height: 1.6; max-width: 34rem;
         margin: 4rem auto; padding: 0 1.25rem; color: #1a1a1a; background: #fff; }}
  .summary {{ font-size: 1.15rem; font-weight: 600; margin: 0 0 .5rem; }}
  .meta {{ color: #666; font-size: .9rem; }}
  pre {{ background: #f5f5f5; padding: .75rem 1rem; border-radius: 6px;
        overflow-x: auto; font-size: .85rem; }}
  input[type=text] {{ font: inherit; padding: .5rem; width: 100%; box-sizing: border-box;
                     border: 1px solid #ccc; border-radius: 6px; }}
  button {{ font: inherit; padding: .6rem 1.4rem; background: #1a1a1a; color: #fff;
           border: 0; border-radius: 6px; cursor: pointer; margin-top: 1rem; }}
  .notice {{ padding: .75rem 1rem; border-radius: 6px; background: #f5f5f5; }}
  .error {{ background: #fdecea; }}
</style></head><body>
{body}
</body></html>
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(title=html.escape(title), body=body), status_code=status)


def _notice(title: str, message: str, status: int = 200, error: bool = False) -> HTMLResponse:
    return _page(
        title,
        f'<h1>{html.escape(title)}</h1>'
        f'<p class="notice{" error" if error else ""}">{html.escape(message)}</p>',
        status=status,
    )


def _render_payload(payload: dict[str, Any]) -> str:
    """Show the approver exactly what will be acted on.

    Escaped, because every value here originated with the model, which may
    be repeating text it read from somewhere hostile. An approval page
    that can be styled by the thing being approved is worse than no
    approval page.
    """
    return html.escape(json.dumps(payload, indent=2, sort_keys=True, default=str))


async def approval_page(request: Request) -> HTMLResponse:
    """GET: show what's being asked and ask for confirmation. No effects."""
    token = request.path_params["token"]
    record = pending_requests.get(settings.pending_requests_path, token)

    if record is None:
        return _notice("Not found", "This approval link is not valid.", 404, error=True)
    if record.status != "pending":
        who = f" by {record.approved_by}" if record.approved_by else ""
        return _notice("Already handled", f"This request was already approved{who}.", 409, error=True)
    if record.is_expired:
        return _notice(
            "Expired",
            "This approval link has expired. Ask for the action to be requested again.",
            410,
            error=True,
        )

    try:
        summary = approvals.get(record.capability).summarize(record.payload)
    except KeyError:
        return _notice(
            "Unavailable",
            f"This request is for '{record.capability}', which this server no longer offers.",
            409,
            error=True,
        )

    body = f"""
      <h1>Approve this action?</h1>
      <p class="summary">{html.escape(summary)}</p>
      <p class="meta">Requested {html.escape(record.created_at)} &middot; expires {html.escape(record.expires_at)}</p>
      <p>Nothing has run yet. It will run when you press the button below.</p>
      <pre>{_render_payload(record.payload)}</pre>
      <form method="post">
        <label for="approved_by">Your name, for the record</label>
        <input type="text" id="approved_by" name="approved_by" required autocomplete="name">
        <button type="submit">Approve and run</button>
      </form>
    """
    return _page("Approve this action?", body)


async def approval_submit(request: Request) -> HTMLResponse:
    """POST: actually run it. Reached only by pressing the button."""
    token = request.path_params["token"]
    form = await request.form()
    approved_by = str(form.get("approved_by") or "").strip() or "unnamed approver"

    try:
        result = approvals.approve(token, approved_by=approved_by)
    except LookupError as error:
        return _notice("Not approved", str(error), 409, error=True)
    except Exception as error:  # noqa: BLE001 - the request is burned either way; show why
        # report(), not str(error) inline: this page is reachable by
        # clicking a link in an email, so whoever's looking at it isn't
        # necessarily the person who wrote the code that raised - the
        # same reasoning as chat_app/errors.py, applied to an approver
        # instead of a chat transcript.
        safe_message = report(error, context="running an approved action")
        return _page(
            "Failed",
            "<h1>Approved, but it failed</h1>"
            '<p class="notice error">The action was approved and started, but did not '
            "complete. It will not run again on its own - this link is now used up.</p>"
            f"<pre>{html.escape(safe_message)}</pre>",
            status=500,
        )

    return _page(
        "Done",
        f"<h1>Done</h1><p class=\"meta\">Approved by {html.escape(approved_by)}.</p>"
        f"<pre>{html.escape(result)}</pre>",
    )


def install_approval_routes(app: Starlette) -> None:
    """Add the approval routes to an existing Starlette app."""
    app.add_route("/approvals/{token}", approval_page, methods=["GET"])
    app.add_route("/approvals/{token}", approval_submit, methods=["POST"])

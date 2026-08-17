"""The fixed catalog of permission scopes a role can be granted, and which
Flask endpoints each one covers.

Deliberately a hardcoded mapping from scope name to a set of endpoint
names, not a free-text route pattern an admin types into a form. Matching
arbitrary strings against request paths is exactly the kind of thing
that's easy to get subtly wrong - trailing slashes, prefixes, query
strings - in a way that either locks someone out or, worse, lets them
through to something they shouldn't reach. Flask's own endpoint names
(``"blueprint.view_func"``) are already a stable, unambiguous identifier
for "which view handles this," resolved by Flask's own router before
``before_request`` runs - so a scope is just a set of those, and the admin
UI in pages/account/ offers scopes as checkboxes rather than a text field.
"""

from __future__ import annotations


ADMIN_ROLE = "admin"
DEFAULT_ROLE = "member"
# Above admin, not a scope bundle - see ROLE_RANK and EXECUTIVE_ENDPOINTS
# below for why this can't just be "admin plus a 'logs' scope": admin's
# scopes are literally "every entry in SCOPES, including ones added
# later" (see parse_scopes), so any scope this role catalog knows about,
# admin already has. Executive's extra reach (the Logs page, and the
# authority to grant/revoke ranked roles - see auth/service.py and
# pages/account/routes.py) has to live outside the scope system
# entirely, or admin would silently inherit it too.
EXECUTIVE_ROLE = "executive"

# Only the three built-in tiers are ranked; every custom role (created via
# the account manager's "Create role" tab) is unranked - rank 0, same as
# the default member tier - since custom roles are just scope bundles,
# not a position in a hierarchy. See auth/service.py's current_rank() and
# pages/account/routes.py's rank checks for how this gates who can
# promote/demote/delete whom.
ROLE_RANK: dict[str, int] = {
    DEFAULT_ROLE: 0,
    ADMIN_ROLE: 1,
    EXECUTIVE_ROLE: 2,
}


def role_rank(name: str) -> int:
    """0 for any name not in ROLE_RANK - member and every custom role."""
    return ROLE_RANK.get(name, 0)

SCOPES: dict[str, dict[str, object]] = {
    "chat": {
        "label": "Chat",
        "endpoints": {
            "chat.static",
            "chat.chat_page",
            "chat.providers_api",
            "chat.extensions_api",
            "chat.add_extension_api",
            "chat.remove_extension_api",
            "chat.chat_api",
            "chat.list_chats_api",
            "chat.get_chat_api",
            "chat.rename_chat_api",
            "chat.delete_chat_api",
        },
    },
    "capabilities": {
        "label": "Capabilities browser",
        "endpoints": {
            "capabilities.static",
            "capabilities.browse",
            "capabilities.api_tools",
            "capabilities.api_resources",
            "capabilities.try_tool",
            "capabilities.read_resource_route",
        },
    },
    "invites": {
        "label": "Generate invite codes",
        "endpoints": {"auth.create_invite"},
    },
    "accounts": {
        "label": "Account manager (create/remove users, manage roles)",
        "endpoints": {
            "account.static",
            "account.manage_page",
            "account.create_user_api",
            "account.delete_user_api",
            "account.set_role_api",
            "account.create_role_api",
            "account.delete_role_api",
            "account.create_invite_api",
            "account.delete_invite_api",
            "account.create_gate_code_api",
            "account.delete_gate_code_api",
            # Not "invites" like auth.create_invite: minting a gate code
            # switches the network gate on for the WHOLE app (see
            # security.check_auth / auth.service.network_gate_enabled),
            # not just for the minting user - too consequential for the
            # default member-level "invites" scope every account gets.
            "auth.create_gate_code",
        },
    },
}

# Reachable by any logged-in user regardless of role - the app's own hub
# page and the ability to leave. Not folded into a scope: a role with zero
# scopes granted must still land somewhere that isn't a 403, and must
# always be able to log out. shared.static is the sidebar's own CSS/JS -
# every page that has a sidebar needs it regardless of which scopes that
# page itself requires.
ALWAYS_ALLOWED_ENDPOINTS = {"overview.index", "overview.static", "auth.logout", "shared.static"}

# The Logs page (chat transcripts and error tracebacks - see
# services/logs_reader.py) - deliberately outside SCOPES, checked
# separately in security.check_role_permission() against
# auth.service.is_executive() instead of a role's granted scopes. Same
# reasoning as EXECUTIVE_ROLE above: putting this in SCOPES would make
# admin inherit it automatically, which defeats the entire point of a
# tier above admin.
EXECUTIVE_ENDPOINTS = {
    "logs.static",
    "logs.logs_page",
    "logs.list_chat_log_users_api",
    "logs.list_user_chat_logs_api",
    "logs.get_chat_log_api",
    "logs.list_error_logs_api",
    "logs.get_error_log_api",
}


def parse_scopes(raw: str) -> set[str]:
    """"*" (the admin role's stored value) means every current scope, not
    a literal scope named "*" - so admin automatically gains access to any
    scope added to SCOPES later, without a matching database migration."""
    if raw == "*":
        return set(SCOPES.keys())
    return {entry for entry in raw.split(",") if entry}


def format_scopes(scopes: set[str]) -> str:
    return ",".join(sorted(scopes))


def endpoint_allowed(scopes: set[str], endpoint: str | None) -> bool:
    if endpoint in ALWAYS_ALLOWED_ENDPOINTS:
        return True
    if endpoint is None:
        return False
    return any(endpoint in SCOPES[scope]["endpoints"] for scope in scopes if scope in SCOPES)

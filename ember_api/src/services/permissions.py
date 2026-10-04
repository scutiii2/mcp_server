"""Every permission ember_api knows about. The Administrator role always
holds all of them (see AuthService.ensure_bootstrap_admin)."""

CHAT_USE = "chat.use"
TOOLS_USE = "tools.use"
ADMIN_MANAGE = "admin.manage"
WATCHERS_VIEW = "watchers.view"
LOGS_VIEW = "logs.view"
LOGS_ERRORS_VIEW = "logs.errors.view"
LOGS_CHAT_VIEW = "logs.chat.view"
CONFIG_ISSUES_VIEW = "config.issues.view"

ALL_PERMISSIONS: dict[str, str] = {
    CHAT_USE: "Chat with ai_agent instances",
    TOOLS_USE: "List and run mcp_server tools",
    ADMIN_MANAGE: "Manage accounts, roles, invites and mcp_server extensions",
    WATCHERS_VIEW: "See the status of mcp_server's background watchers",
    LOGS_VIEW: "Read the activity log (logins, account and admin changes)",
    LOGS_ERRORS_VIEW: "Read the error log",
    LOGS_CHAT_VIEW: "Read the chat-turn log (every account's questions and answers)",
    CONFIG_ISSUES_VIEW: "See problems in ember_api's config and secret files",
}

ADMIN_ROLE = "Administrator"

# What the default role (config_app.json's default_role) starts with when it
# has to be created. Only applied on creation: later edits by an admin stick.
DEFAULT_ROLE_PERMISSIONS = (CHAT_USE, TOOLS_USE)

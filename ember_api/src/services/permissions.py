"""Every permission ember_api knows about. The Administrator role always
holds all of them (see AuthService.ensure_bootstrap_admin)."""

CHAT_USE = "chat.use"
TOOLS_USE = "tools.use"
ADMIN_MANAGE = "admin.manage"

ALL_PERMISSIONS: dict[str, str] = {
    CHAT_USE: "Chat with ai_agent instances",
    TOOLS_USE: "List and run mcp_server tools",
    ADMIN_MANAGE: "Manage accounts, roles and invites",
}

ADMIN_ROLE = "Administrator"

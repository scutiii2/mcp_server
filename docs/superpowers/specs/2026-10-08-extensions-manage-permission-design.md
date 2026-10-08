# Capabilities supermarket, phase 2: the `extensions.manage` permission

Date: 2026-10-08. Projects: `ember_api`, `ember_web`. Status: written, awaiting review.

Phase 2 of 3. Phase 1 (account-level enabled state and the Supermarket) is merged. Phase 3 (private, per-account extensions) is a separate spec.

## Goal

Adding or removing a server-listed extension (another MCP server that `mcp_server` offers to every client) is today gated by `admin.manage`, the permission that also covers accounts, roles, invites and usage. Give it its own permission, `extensions.manage`, so an account can manage extensions without being able to manage accounts, and the other way round.

## Decisions

| Question | Decision |
|---|---|
| Name | `extensions.manage`. |
| Does `admin.manage` still allow it | No. The two are independent. `POST` and `DELETE /api/extensions` require `extensions.manage` only. |
| Who holds it by default | The Administrator role, which always holds every permission in `ALL_PERMISSIONS`. No other role gets it automatically, including the default role. |
| Roles that hold `admin.manage` today | They lose the ability to add and remove extensions until an admin grants them `extensions.manage` in the Admin page. The only account today is the owner's, which is Administrator, so nothing changes in practice. |
| Existing data | No migration. Permissions are defined in code (`services/permissions.py`); startup creates a missing `Permission` row and gives the Administrator role every permission. |
| Listing extensions | Unchanged: `GET /api/extensions` needs `chat.use` or `tools.use`. |
| Turning a built-in capability on or off for everyone (`PATCH /api/capabilities/{name}`) | Unchanged: still `admin.manage`. |

Out of scope: any change to what extensions do, per-account private extensions (phase 3), and a database migration.

## ember_api

### Permission

In `src/services/permissions.py`:

- Add `EXTENSIONS_MANAGE = "extensions.manage"`.
- Add it to `ALL_PERMISSIONS` with the description `"Add and remove mcp_server extensions (other MCP servers offered to every client)"`.
- Change the `ADMIN_MANAGE` description to `"Manage accounts, roles, invites and settings everyone is held to"`. It no longer mentions extensions. Keep the wording honest about what `admin.manage` still covers (accounts, roles, invites, usage totals, the `force_tool_approval` setting, capability on/off for everyone).
- `DEFAULT_ROLE_PERMISSIONS` stays `(CHAT_USE, TOOLS_USE)`.

### Routes

In `src/routes/server_info.py`:

- Add `require_extensions_manage = require_permission(EXTENSIONS_MANAGE)`.
- `POST /api/extensions` and `DELETE /api/extensions/{extension_id}` use `require_extensions_manage` instead of `require_admin`.
- `PATCH /api/capabilities/{name}` keeps `require_admin`.
- Update the module docstring: switching a capability needs `admin.manage`; adding or removing an extension needs `extensions.manage`. Both are written to the activity log.

The activity log entries (`mcp.extension_add`, `mcp.extension_remove`) are unchanged.

### Docs

In `README.md`, change the permission column of the `POST /api/extensions` and `DELETE /api/extensions/{id}` rows from `admin.manage` to `extensions.manage`, and add `extensions.manage` to any list of permissions (search the README for `watchers.view` or `traffic.view` to find it).

## ember_web

- `src/views/SupermarketView.vue`: add `const canManageExtensions = computed(() => auth.hasPermission("extensions.manage"))`. The **Add extension** button, the `AddExtensionModal`, the per-row **Remove** button and the remove confirmation use `canManageExtensions`. `isAdmin` (`admin.manage`) stays only for the **Turn on for everyone** button on a capability that is off for everyone.
- `src/api/ExtensionsClient.ts`: update the doc comment to "adding/removing extensions.manage".
- `src/views/CapabilitiesView.vue`: unchanged (`admin.manage` there only guards the capability "everyone" switch).
- The Admin page lists permissions from `GET /api/admin/permissions`, so `extensions.manage` appears there and can be granted to a role with no further change. Check this by reading `AdminView` and its components and confirm nothing hard-codes the permission list; if something does, add the new one.
- `e2e/fakeApi.ts`: add `extensions.manage` to the administrator account's permissions and to the `ADMIN_PERMISSIONS` list, so the Supermarket e2e test that adds an extension keeps working.

## Testing

`ember_api` (pytest, in `tests/test_server_info.py` and `tests/test_admin.py`):

- A member whose role holds only `chat.use` and `extensions.manage` can `POST /api/extensions` (201) and `DELETE /api/extensions/{id}` (204). Both are logged.
- A member whose role holds `admin.manage` but not `extensions.manage` gets 403 on both.
- A member with `extensions.manage` but not `admin.manage` still gets 403 on `PATCH /api/capabilities/{name}` and on `GET /api/admin/accounts`.
- The Administrator role holds `extensions.manage` after startup; the default role does not.
- `GET /api/admin/permissions` lists `extensions.manage` with its description, and `admin.manage` with the new description.
- The existing admin extension test keeps passing (the bootstrap admin holds both).
- Use the helpers already in `tests/test_admin.py` (`make_member`, `login`, `role_by_name`) and the role-permission routes (`PUT /api/admin/roles/{id}/permissions/{name}`) to build the roles.

`ember_web` (vitest, `src/views/SupermarketView.test.ts`):

- An account with `admin.manage` but not `extensions.manage` sees neither **Add extension** nor **Remove**, but does see **Turn on for everyone** on a capability that is off for everyone.
- An account with `extensions.manage` but not `admin.manage` sees **Add extension** and **Remove**, and does not see **Turn on for everyone**.
- Rewrite the existing "add and remove extensions; others see neither" test to use `extensions.manage` instead of `admin.manage`, and the existing admin tests that remove an extension and that turn a capability back on for everyone to use the right permission each.
- Playwright `e2e/capabilities.spec.ts` still passes.

## Work breakdown

1. ember_api: permission constant and description, route dependency swap, docstring, README, and the tests above. Test first.
2. ember_web: `canManageExtensions` split in `SupermarketView.vue`, `ExtensionsClient.ts` comment, `fakeApi.ts`, `ExtensionsClient`/view tests, README line for the Supermarket, then the full suite, `npm run build` and the Playwright spec.

Each task is committed on its own. Run the full `ember_api` and `ember_web` suites at the end.

# ember_admin

Admin web app for ember, built with Vue 3, TypeScript and Vite. It runs on
port 5175 (`EMBER_ADMIN_PORT`) and talks only to [ember_api](../ember_api)
over the same origin, like [ember_web](../ember_web): its Vite server forwards
`/api` to ember_api, so the browser holds no server URL or token.

## Run

Needs `ember_api` and `mcp_server` running (ember_api proxies the capability
and extension calls to mcp_server).

- `run.bat` installs `node_modules` on first run, then starts Vite. Extra
  arguments go to Vite.
- `server_launcher` lists it as **Ember Admin** (detected from `run.bat`).
- `npm run dev`

Open <http://127.0.0.1:5175> and log in with an account that has
at least one of the page permissions below. A login made in ember_web also works here: cookies are not
scoped by port, so the same ember_api session cookie is sent.

| Env var | Default | Meaning |
|---|---|---|
| `EMBER_ADMIN_PORT` | `5175` | Vite's port. |
| `EMBER_API_PORT` | `8030` | Where Vite forwards `/api` (ember_api). |

## Pages

| Page | Needs |
|---|---|
| Capabilities (`/capabilities`) | `capabilities.manage` |
| Extensions (`/extensions`) | `extensions.manage` |
| Analytics (`/analytics`) | any of `logs.view`, `logs.errors.view`, `logs.chat.view`, `traffic.view` |
| Workspace overview (`/admin`) | any account, role, invitation, or workspace settings permission |
| Accounts (`/admin/accounts`) | any of `accounts.view`, `accounts.manage`, `accounts.delete`, `roles.assign` |
| Roles & permissions (`/admin/roles`) | any of `roles.view`, `roles.manage`, `roles.assign` |
| Invites (`/admin/invites`) | `invites.manage` |
| Workspace settings (`/admin/settings`) | `settings.manage` |

The router and the nav read one list (`src/router/pages.ts`). A user with none
of these sees the no-access page. ember_api enforces every permission itself;
the UI only decides what to show.

## Capabilities

One card per mcp_server capability, with an online switch.

- **Offline** hides the capability's tools from every client.
- **Online** loads the capability's code from disk again, so an edit takes
  effect: switch it offline, edit, switch it online.
- **Refresh** finds capability folders added while mcp_server runs and lists
  them offline. A new folder is never loaded until you switch it online.
- A failed online keeps the capability offline and shows its load error on the
  row. A folder deleted from disk shows as missing.
- A switch stays pending until the server answers; it never shows a state the
  server did not confirm.

Only the capability's own folder is re-imported. Shared modules in
`mcp_server/src/services` are not: restart mcp_server for those. Do not reload
the watchers capability while its watchers run.

The first mcp_server run with the folder scanner writes `enabled: true` for
every existing capability and a `_scanner` marker into
`mcp_server/configs/config_capabilities.json` (gitignored). After that, a
folder with no entry starts offline. See
[mcp_server/configs/README.md](../mcp_server/configs/README.md).

## Extensions

Lists the extensions mcp_server proxies, adds one (name, URL, optional
description) and removes one after a confirm dialog. Extensions are not
reloaded from here.

## Admin and Analytics

Admin and Analytics live only in ember_admin. ember_web keeps personal preferences,
capability/tool browsing, and private extensions; shared extension management and
global capability switches live here.

The shell uses ember_web's Ember mark, 52px icon rail, named hover/focus labels,
and bottom navigation below 768px. Theme cycles through System, Light, and Dark
and persists in this browser, including on the login page. Page content scrolls
independently of navigation; controls use the same theme and radius tokens.

Overview, Accounts, Roles & permissions, Invites, and Workspace settings sit
directly in the main icon rail, alongside Capabilities, Extensions, and Analytics.
There is one navigation sidebar, with the current page marked individually.
The app opens the workspace overview by default, or the first permitted page
for accounts with only capability, extension, or analytics access. Below 768px
the page links scroll horizontally in the bottom rail while theme and sign-out
controls remain visible. Each page checks its own permissions; restricted
administrators see only the destinations and actions they can access.

The overview shows permitted account and invite counts, links to filtered
account lists, and shortcuts to the administration pages. Accounts keep search
and status filters in the URL (`q`, `status`) across reload and browser navigation.
Account details and invite creation use native dialog drawers, with keyboard
focus contained while open; on mobile they sit above the bottom rail. Invite
codes remain visible only immediately after creation.

Role permissions have friendly labels and keys, grouped into Chat & files,
Tools & personal extensions, Accounts & access, and Workspace & monitoring.
Search matches the label, key, or server description. Switches retain the
server-confirmed state while saving, and protected roles remain locked.
Workspace settings remain drafts until saved through the unsaved-change bar.

Old bookmarks such as `/admin?tab=roles` redirect to `/admin/roles`, preserving
other query options and the fragment. `/admin/invites?create=1` opens the invite
drawer and removes the transient creation flag from the URL.

## Tests

```bash
npm test
npx vue-tsc -b
npm run test:e2e
```

`npm test` runs Vitest with jsdom (`*.test.ts` beside the source).
`npx vue-tsc -b` type-checks the app and its tests. `npm run test:e2e` runs
Playwright against the built app on port 5198 (`EMBER_E2E_PORT`) in the
Chrome installed on this machine. `e2e/fakeApi.ts` answers every `/api` call,
so ember_api is not needed.

### Granular permissions

Ember now separates tool browsing (`tools.view`) from execution (`tools.execute`),
including tools called through chat. Public link creation needs `chat.share`,
personal MCP connection changes need `extensions.personal.manage`, and file
transfers use `files.upload` / `files.download`. Existing roles retain equivalent
access through the one-time API migration; role editors list the new permissions.

Administration uses `accounts.view`, `accounts.manage`, `accounts.delete`,
`roles.view`, `roles.manage`, `roles.assign`, `invites.manage`, and
`settings.manage`. Shared capability controls use `capabilities.manage`; shared
extension management remains `extensions.manage`. The all-account usage report
uses `usage.all.view`. Navigation and controls follow these permissions, and the
API enforces every action. Delegated administrators can only grant or change
roles within their own permissions.

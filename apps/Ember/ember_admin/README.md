# ember_admin

Admin web app for ember, built with Vue 3, TypeScript and Vite. It runs on
port 5176 (`EMBER_ADMIN_PORT`) and talks only to [ember_api](../ember_api)
over the same origin, like [ember_web](../ember_web): its Vite server forwards
`/api` to ember_api, so the browser holds no server URL or token.

## Run

Needs `ember_api` and `mcp_server` running (ember_api proxies the capability
and extension calls to mcp_server).

- `run.bat` installs `node_modules` on first run, then starts Vite. Extra
  arguments go to Vite.
- `server_launcher` lists it as **Ember Admin** (detected from `run.bat`).
- `npm run dev`

Open <http://127.0.0.1:5176> and log in with an account that has
at least one of the page permissions below. A login made in ember_web also works here: cookies are not
scoped by port, so the same ember_api session cookie is sent.

| Env var | Default | Meaning |
|---|---|---|
| `EMBER_ADMIN_PORT` | `5176` | Vite's port. |
| `EMBER_API_PORT` | `8030` | Where Vite forwards `/api` (ember_api). |

## Pages

| Page | Needs |
|---|---|
| Capabilities (`/capabilities`) | `capabilities.manage` |
| Extensions (`/extensions`) | `extensions.manage` |
| Agents (`/agents`) | `agents.manage` |
| Analytics (`/analytics`) | any of `logs.view`, `logs.errors.view`, `logs.chat.view`, `traffic.view` |
| Workspace overview (`/admin`) | any account, role, invitation, or workspace settings permission |
| Accounts (`/admin/accounts`) | any of `accounts.view`, `accounts.manage`, `accounts.delete`, `roles.assign` |
| Roles & permissions (`/admin/roles`) | any of `roles.view`, `roles.manage`, `roles.assign` |
| Invites (`/admin/invites`) | `invites.manage` |
| Workspace settings (`/admin/settings`) | `settings.manage` |
| Profile (`/profile`; `/account` redirects here) | any logged-in account |
| Personal settings (`/settings`) | any logged-in account |
| Email verification (`/verify-email`) | any logged-in account |

The router and the nav read one list (`src/router/pages.ts`). A user with none
of these sees the no-access page. ember_api enforces every permission itself;
the UI only decides what to show.

Profile mirrors Ember Web's account page: identity and email status, password
and email changes, roles and permissions, remembered devices, theme, and sign-out.
Email changes that require verification open the verification page here; Profile
stays available while permissions are paused so the account can correct its email.

Personal Settings uses Ember Web's appearance and sidebar controls, with searchable
settings, modified indicators, and individual resets. Theme and sidebar changes
stay as drafts until saved through the bottom Save/Revert bar. Revert restores
the saved preferences; leaving with a draft asks before discarding it, and
reloading warns about unsaved changes. The bar sits above the mobile navigation.
Sidebar order, pins, and hidden pages are stored
per account in this browser, independently of Ember Web. Hidden administration
pages stay reachable from the workspace overview; Profile and Settings always stay
in the rail. Workspace settings continue to control server-wide policy separately.

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
[mcp_server/configs/README.md](../../mcp_server/configs/README.md).

## Agents

Lists ai_agent's agent files as cards like ember_web's (plus port, URL and the Edit and Remove buttons) with their live status (running, offline, disabled; the status needs `chat.use`, otherwise it is left out). **New agent** and **Edit** open a form: id (fixed once created), name, port, URL (where ember and the other agents reach it; empty = this machine and the port), provider, gateway (filtered by the provider), model, reasoning effort, strongest tier, persona, instructions, focus, allowed/denied tool globs, and the enabled, orchestrator and entry switches. Fields the form does not show are kept when saving. The form also edits the identity override, temperature, max tokens, max tool rounds, the highest effort a delegator may request, the weakest and strongest tier (with a preview of the model each tier resolves to). **Show prompt** builds the full system prompt the model receives from the draft and the shared prompts. **Shared prompts** (button in the page header) edits the text every agent shares: assistant name and description, the identity line template, the default instructions, the specialist list intro and the caveman rule; each has a reset to its default, and saving asks first because it restarts every agent. Remove asks for the agent id; the entry agent cannot be removed. ai_agent validates every change (refusals such as a port clash show in the form) and its supervisor starts, restarts or stops the agent within a few seconds. Needs a running agent to reach ai_agent.

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

The Ember logo opens the workspace overview. Accounts, Roles & permissions,
Invites, and Workspace settings sit directly in the main icon rail, alongside
Capabilities, Extensions, and Analytics. There is no separate Overview icon
or breadcrumb trail.
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

Role details and permissions are drafts. A fixed bottom Save/Revert bar appears while changes are pending; Save applies them together in one request. Leaving or switching roles asks before discarding a draft. Accounts with account-list access can open View affected accounts to see who holds the role.

Capabilities and extensions appear as cards. Open a card to see its tools, then select a tool to use its parameter form and run it. Tool details require `tools.view` or `tools.execute`; running requires `tools.execute`. Offline or disconnected tools cannot be tested. Tests execute the real tool through the existing MCP proxy.

The integration modal uses a searchable tool browser beside the parameter form and output on desktop, stacked on mobile. Its header shows the integration identity and availability; tool output is formatted as JSON when possible.

Content pages share heading typography, description typography, and horizontal spacing through `ember_web/src/components/pageLayout.css` (also imported by Ember Admin).

Capabilities and extensions can be searched by their names and contributed tool names. Extension descriptions are also searchable; filtering does not change enabled state.

Overview uses the same permission-filtered page list as the main sidebar. Permission and account-state switches use native change events so their appearance follows the draft or confirmed server state.

The Roles page keeps its heading fixed while the role list and permission options scroll independently. On mobile, the role picker scrolls horizontally above the permission panel.

## Mobile and installation

Phone layouts use bottom navigation, touch controls, safe-area padding for notches
and the home indicator, and the dynamic viewport for browser chrome and keyboards.
Ember and Ember Admin install separately, each from its own origin.

Build with `npm run build`, then serve `dist/` over HTTPS (localhost also works).
For phone layout testing on the same Wi-Fi, run `npm run preview -- --host 0.0.0.0`
and open this computer's LAN address and preview port; use an HTTPS reverse proxy
for installation and offline testing on a phone.
The browser can install the app from its menu; when an install prompt is available,
an **Install app** button appears. On iPhone/iPad, use Safari → Share → Add to Home Screen.
The PWA service worker is enabled in production builds, including `npm run preview`,
and is disabled in the Vite development server so it does not interfere with HMR.
An HTTP LAN address can serve the mobile layout, but installation/offline support
requires HTTPS. Keep the existing same-origin `/api` proxy and SPA route fallback.
Serve `sw.js` and `index.html` with revalidation (`Cache-Control: no-cache`), hashed
`assets/` with immutable caching, and the manifest as `application/manifest+json`.

After one connected visit, static HTML, JavaScript, CSS and app icons are available
offline. An offline banner explains that chat, sign-in and administration actions
need a connection; use **Retry** once connected. The service worker never caches
API responses, transcripts, account data or generated downloads, and never queues
or replays writes. A cold offline start cannot restore the server session.
New builds show **Reload to update** / **Later**; save drafts first. There is no
automatic update reload during a chat or an administration edit.

App icons: `public/icons/`. Regenerate both sets from their SVG logos with
`node ../scripts/generate-pwa-icons.mjs` (from either app; uses local Chrome).
Production browser tests cover phone layouts, installation metadata, offline shell
loading, API cache exclusion and reconnection.

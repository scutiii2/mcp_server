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
`admin.manage`. A login made in ember_web also works here: cookies are not
scoped by port, so the same ember_api session cookie is sent.

| Env var | Default | Meaning |
|---|---|---|
| `EMBER_ADMIN_PORT` | `5175` | Vite's port. |
| `EMBER_API_PORT` | `8030` | Where Vite forwards `/api` (ember_api). |

## Pages

| Page | Needs |
|---|---|
| Capabilities (`/capabilities`) | `admin.manage` |
| Extensions (`/extensions`) | `admin.manage` or `extensions.manage` (adding and removing need `extensions.manage` in ember_api) |
| Analytics (`/analytics`) | any of `logs.view`, `logs.errors.view`, `logs.chat.view`, `traffic.view` |
| Admin (`/admin`) | `admin.manage` |

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

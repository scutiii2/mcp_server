# Agent registry over HTTP (ai_agent on another machine)

Status: implemented 2026-10-05, not committed. Change from the plan: `AI_AGENT_ADVERTISE_URL` may omit the port, and each instance then adds its own, so one value serves every supervised agent.

## Goal

ember_api finds ai_agent instances through a URL, not a file path, so ai_agent can run in another directory or on another machine.

## Today

- ai_agent writes `ai_agent/data/agent_registry.json` (`agent_registry.register()` / `deregister()`, called from `ai_agent/src/server.py` `main()`).
- ember_api reads that file: `Settings.agents_registry_path` (`ember_api/src/config.py:140`, `configs/config_app.json:10`) feeds `AgentDirectory` (`ember_api/src/services/agent_directory.py`).
- Other readers of the path: `services/config_validation.py:237` (`collect_issues`), `scripts/import_chat_app.py` (`check_agents`), `routes/mcp.py:32`.
- Chat traffic already goes by URL (`AgentEntry.url`). Only discovery uses the filesystem.
- `server.py:103` registers `http://127.0.0.1:PORT/mcp` when `AI_AGENT_HOST` is `0.0.0.0`. A remote ember_api cannot reach that.
- `InternalTokenMiddleware` guards only `/mcp` (`internal_auth.PROTECTED_PATH`).

## Design

1. ai_agent serves its registry at `GET /registry` (same JSON as the file, `{"agents": [...]}`), guarded by `X-Internal-Token`.
2. ember_api gets `agents_registry_url`. `AgentDirectory` fetches it (short cache, stale-on-error). `agents_registry_path` stays as the local-dev fallback; when both are set, the URL wins.
3. ai_agent gets `AI_AGENT_ADVERTISE_URL` (base URL peers use, e.g. `http://10.0.0.5:9100`). It overrides the host-derived URL in `_AGENT_URL`.

Any ai_agent instance can serve `/registry`, because supervised children on one machine share one registry file. ember_api points at one of them (normally the entry agent). If that instance is down the directory is empty, the same as today when no agent runs. Multi-machine fleets with no shared file are out of scope: use a static `agents` list in ember_api config for that (separate change).

## Steps

### ai_agent

1. `src/core/internal_auth.py`: replace `PROTECTED_PATH` with a tuple `PROTECTED_PATHS = ("/mcp", "/registry")`; `_protects` checks each prefix. Update the class docstring.
2. `src/server.py`:
   - Read `AI_AGENT_ADVERTISE_URL`; when set, `_AGENT_URL = f"{advertise.rstrip('/')}/mcp"`. Validate it is `http(s)://host[:port]` with no path; exit with the existing one-line config error style if not.
   - Add a route with `@mcp.custom_route("/registry", methods=["GET"])` that calls `agent_registry.reload()` and returns `JSONResponse({"agents": agent_registry.all_agents()})`.
3. `README.md` / `src/README.md`: document `AI_AGENT_ADVERTISE_URL` and `/registry`.
4. Tests (`tests/test_server.py`, `tests/test_internal_auth.py`): `/registry` returns the agents; 401 without the token when one is set; advertised URL overrides the host-derived one; a bad advertise value is rejected.

### ember_api

5. `src/config.py` and `config_validation.py`: add `agents_registry_url: str | None` (`_is_text`, must start with `http://` or `https://`). Keep `agents_registry_path`.
6. `src/services/agent_directory.py`: add a source abstraction with two implementations, `FileRegistrySource` (current `_read`) and `HttpRegistrySource` (shared `httpx.AsyncClient`, 3 s timeout, `X-Internal-Token` from the same setting `agent_gateway` uses, 5 s cache, return last good list on error and log a warning). `AgentDirectory` takes a source; entry selection logic is unchanged. Move the JSON-to-`AgentEntry` parsing into one shared function.
7. `src/routes/mcp.py:32` and `src/app.py`: build the directory from settings (URL source if `agents_registry_url`, else file source).
8. `services/config_validation.py:237`: when a URL is set, skip the file read and `_check_agents` runs on the fetched JSON in `collect_issues_async` (the sync `collect_issues` must not do network I/O; add a warning-only reachability check in the async path).
9. `scripts/import_chat_app.py` `check_agents`: use `AgentDirectory` instead of reading the path.
10. Tests: extend `tests/test_agent_directory.py` (HTTP source: ok, 401, timeout keeps last good, malformed body is empty) using the existing fake upstream in `tests/conftest.py`; update `test_import_chat_app.py` fixtures.

### Docs and vault

11. `docs/2026-09-25-ember-changes-to-existing-projects.md` mentions `agents_registry_path`; add the URL option.
12. After merge, run the project-sync skill for `Brain/Projects/ai_agent.md` and `ember_api.md`, and log the decision (registry served over HTTP) with decision-log.

## Deployment checklist (remote machine)

- `AI_AGENT_HOST=0.0.0.0`, `AI_AGENT_ADVERTISE_URL=http://<reachable-host>` (no port when run.bat starts several agents).
- Same `INTERNAL_API_TOKEN` on both machines.
- Open the port in the firewall; use a private network or TLS (the token is sent in a header).
- ember_api: `agents_registry_url: "http://<host>:<port>/registry"`.

## Risks and open questions

- Token exposure over plain HTTP between machines. Recommend VPN or a TLS reverse proxy; no code change here.
- `/registry` lists agent URLs, so it must stay behind the token. Do not exempt it.
- Does `agent_gateway` already hold the internal token and an HTTP client ember_api can reuse for step 6? Check before adding a new client.
- Single point of discovery (one instance serves `/registry`). Acceptable for v1.

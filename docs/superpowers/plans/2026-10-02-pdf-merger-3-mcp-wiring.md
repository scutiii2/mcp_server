# PDF merger wiring (`mcp_server` extension headers, requester forwarding, launcher) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `mcp_server` reach `pdf_merger`'s token-protected `/mcp` as an HTTP extension, pass the asking user along on every proxied call, and wire the new projects into `server_launcher` and the vault.

**Architecture:** HTTP extension entries in `config_extensions.json` gain an optional `headers` object (with `${VAR}` placeholders, resolved like every other value). `ExtensionRegistry` passes those headers to `streamablehttp_client` and forwards the caller's identity as `_meta.requester` on every proxied `tools/call`. Then config and launcher entries connect the pieces.

**Tech Stack:** Python 3.11+, `mcp==1.28.0` (client `streamablehttp_client(url, headers=...)`, `ClientSession.call_tool(..., meta=...)`), pytest + anyio.

**Spec:** `docs/superpowers/specs/2026-10-02-pdf-merger-design.md` (section "Integration").

This is plan 3 of 3. Tasks 1–2 are independent of plans 1 and 2. Task 3 needs both done.

## Global Constraints

- Working directory: `Python/MCPServer/mcp_server` for Tasks 1–2 (`.venv_mcp\Scripts\python -m pytest`). Git commands run in `Python/MCPServer`.
- Follow `mcp_server`'s existing style: long explanatory docstrings where behavior is non-obvious, `ValueError` messages that name the config file and the dotted key.
- `headers` is valid only on an HTTP extension (`url`). On a stdio extension (`command`) it is a config error.
- `headers` must be an object whose keys and values are strings. Values may contain `${VAR}` (resolved by the existing `resolve_section` walk).
- Resolved header values are secrets. They are never written back by `save_extension_config` and never appear in `ExtensionStatus` or any HTTP response.
- Requester forwarding: `_meta = {"requester": {"username": ..., "email": ...}}` when either is non-empty, else no `_meta`. Same key and shape ai_agent already sends (`REQUESTER_META_KEY` in `src/services/identity_context.py`).
- Existing tests must keep passing. Test fakes in `tests/test_extensions.py` must accept the new keyword arguments.

---

### Task 1: `headers` on HTTP extension config

**Files:**
- Modify: `mcp_server/src/services/app_config.py` (`ExtensionConfig` at ~line 134, `_build_extension` at ~line 367)
- Test: `mcp_server/tests/test_app_config.py` (add after `test_http_extension_empty_url_is_rejected`, ~line 593)

**Interfaces:**
- Produces: `ExtensionConfig.headers: dict[str, str]` (default empty dict).

- [ ] **Step 1: Write the failing tests**

Add to `mcp_server/tests/test_app_config.py` after `test_http_extension_empty_url_is_rejected`:

```python
def test_http_extension_headers_resolve_placeholders(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "s3cret")
    path = _write(
        tmp_path,
        {
            "pdf_merger": {
                "label": "PDF Merger",
                "url": "http://127.0.0.1:8040/mcp",
                "headers": {"X-Internal-Token": "${INTERNAL_API_TOKEN}"},
            }
        },
    )

    assert load_extensions_config(path)["pdf_merger"].headers == {"X-Internal-Token": "s3cret"}


def test_http_extension_without_headers_has_none(tmp_path: Path):
    path = _write(tmp_path, {"remote": {"label": "Remote", "url": "http://127.0.0.1:9000/mcp"}})

    assert load_extensions_config(path)["remote"].headers == {}


def test_http_extension_headers_must_be_strings(tmp_path: Path):
    path = _write(tmp_path, {"remote": {"label": "Remote", "url": "http://127.0.0.1:9000/mcp", "headers": {"X-Count": 3}}})

    with pytest.raises(ValueError, match="'remote.headers' must be an object of string values"):
        load_extensions_config(path)


def test_stdio_extension_with_headers_is_rejected(tmp_path: Path):
    path = _write(tmp_path, {"local": {"label": "Local", "command": "python", "headers": {"X": "y"}}})

    with pytest.raises(ValueError, match="'local.headers' only applies to an http extension"):
        load_extensions_config(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_mcp\Scripts\python -m pytest tests/test_app_config.py -q -k headers`
Expected: FAIL with `AttributeError: 'ExtensionConfig' object has no attribute 'headers'` (and the two `ValueError` tests fail with "DID NOT RAISE").

- [ ] **Step 3: Write the implementation**

In `mcp_server/src/services/app_config.py`, add a field at the end of `ExtensionConfig` (after `url: str | None = None`):

```python
    # http transport only: extra HTTP headers sent on every request to the
    # upstream (e.g. {"X-Internal-Token": "${INTERNAL_API_TOKEN}"} for an
    # upstream that, like this server, requires the shared internal token).
    # Values are resolved from the environment at load time, so they are
    # secrets: never persisted by save_extension_config, never reported.
    headers: dict[str, str] = field(default_factory=dict)
```

In `_build_extension`, replace the `if has_url:` block:

```python
    if has_url:
        url = str(required("url")).strip()
        if not url:
            raise ValueError(f"Config file {config_path}: '{id_}.url' must not be empty")
        return ExtensionConfig(id=id_, label=label, description=description, transport="http", url=url)
```

with:

```python
    headers = entry.get("headers", {})
    if "headers" in entry and not has_url:
        raise ValueError(
            f"Config file {config_path}: '{id_}.headers' only applies to an http extension "
            f"(one with 'url'). A stdio extension talks over stdin/stdout and sends no HTTP headers."
        )
    if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
        raise ValueError(f"Config file {config_path}: '{id_}.headers' must be an object of string values")

    if has_url:
        url = str(required("url")).strip()
        if not url:
            raise ValueError(f"Config file {config_path}: '{id_}.url' must not be empty")
        return ExtensionConfig(
            id=id_, label=label, description=description, transport="http", url=url, headers=dict(headers)
        )
```

`save_extension_config` is unchanged on purpose: it writes only `url` for an HTTP entry, so a resolved token can never be written to disk. Add one sentence to its docstring, after "Written by transport: ...":

```python
    ``headers`` is never written: by the time a config reaches here its
    header values are resolved secrets, not ``${VAR}`` placeholders. An
    extension that needs headers is configured by hand in the file.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_mcp\Scripts\python -m pytest tests/test_app_config.py -q`
Expected: PASS (new and existing).

- [ ] **Step 5: Commit**

```bash
git add mcp_server/src/services/app_config.py mcp_server/tests/test_app_config.py
git commit -m "feat(mcp_server): allow headers on http extensions"
```

---

### Task 2: Send headers upstream and forward the requester

**Files:**
- Modify: `mcp_server/src/services/extensions.py` (`_open_and_list` http branch ~line 427; `call` ~line 442; imports ~line 97)
- Test: `mcp_server/tests/test_extensions.py` (update fakes ~lines 45–125; add tests in the "http transport" section)

**Interfaces:**
- Consumes: `ExtensionConfig.headers` (Task 1), `current_username`, `current_email`, `REQUESTER_META_KEY` from `src/services/identity_context.py`.
- Produces: no new public names. Behavior: `streamablehttp_client(config.url, headers=config.headers or None)`; `session.call_tool(..., meta={"requester": {...}})` when an identity is known.

- [ ] **Step 1: Update the test fakes so they accept and record the new arguments**

In `mcp_server/tests/test_extensions.py`:

Replace `_FakeSession.__init__` and `call_tool`:

```python
class _FakeSession:
    def __init__(self, tools: list[types.Tool], call_results: dict[str, types.CallToolResult] | None = None):
        self._tools = tools
        self._call_results = call_results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.metas: list[dict[str, Any] | None] = []
```

```python
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        read_timeout_seconds: object = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        self.calls.append((name, arguments))
        self.metas.append(meta)
        return self._call_results[name]
```

Replace `_fake_streamablehttp_client` and `_fake_streamablehttp_client_raising` so they accept `headers` and record it:

```python
def _fake_streamablehttp_client(session: _FakeSession, seen: list[dict[str, Any]] | None = None):
    @contextlib.asynccontextmanager
    async def _cm(url: str, **kwargs: Any):
        if seen is not None:
            seen.append({"url": url, **kwargs})
        yield (session, None, None)

    return _cm


def _fake_streamablehttp_client_raising(error: Exception):
    @contextlib.asynccontextmanager
    async def _cm(url: str, **kwargs: Any):
        raise error
        yield  # pragma: no cover - unreachable, satisfies the generator protocol

    return _cm
```

`_install_fake_http_connection` keeps its signature; the `seen` list is only used by the new tests below, which call `_fake_streamablehttp_client` directly.

- [ ] **Step 2: Run the existing suite to confirm the fakes still fit**

Run: `.venv_mcp\Scripts\python -m pytest tests/test_extensions.py -q`
Expected: PASS (no behavior change yet).

- [ ] **Step 3: Write the failing tests**

Add to the "http transport" section of `mcp_server/tests/test_extensions.py`:

```python
@pytest.mark.anyio
async def test_http_extension_sends_configured_headers(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(extensions, "streamablehttp_client", _fake_streamablehttp_client(session, seen))
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write, **kwargs: read)
    monkeypatch.setattr(
        extensions,
        "load_extensions_config",
        lambda path: {
            "pdf_merger": _config(
                id="pdf_merger",
                command="",
                transport="http",
                url="http://127.0.0.1:8040/mcp",
                headers={"X-Internal-Token": "s3cret"},
            )
        },
    )

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    assert seen == [{"url": "http://127.0.0.1:8040/mcp", "headers": {"X-Internal-Token": "s3cret"}}]
    [status] = registry.statuses()
    assert "s3cret" not in repr(status)


@pytest.mark.anyio
async def test_http_extension_without_headers_sends_none(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(extensions, "streamablehttp_client", _fake_streamablehttp_client(session, seen))
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write, **kwargs: read)
    monkeypatch.setattr(
        extensions,
        "load_extensions_config",
        lambda path: {"remote": _config(id="remote", command="", transport="http", url="http://127.0.0.1:9000/mcp")},
    )

    await extensions.ExtensionRegistry().connect_all(Path("unused.json"))

    assert seen == [{"url": "http://127.0.0.1:9000/mcp", "headers": None}]


@pytest.mark.anyio
async def test_proxied_call_forwards_the_requester(monkeypatch: pytest.MonkeyPatch):
    result = types.CallToolResult(content=[types.TextContent(type="text", text="hi")])
    session = _FakeSession(tools=[_echo_tool()], call_results={"echo": result})
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})
    monkeypatch.setattr(extensions, "current_username", lambda: "alice")
    monkeypatch.setattr(extensions, "current_email", lambda: "alice@example.com")

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    await registry.call("reference__echo", {"text": "hi"})

    assert session.metas == [{"requester": {"username": "alice", "email": "alice@example.com"}}]


@pytest.mark.anyio
async def test_proxied_call_without_identity_sends_no_meta(monkeypatch: pytest.MonkeyPatch):
    result = types.CallToolResult(content=[types.TextContent(type="text", text="hi")])
    session = _FakeSession(tools=[_echo_tool()], call_results={"echo": result})
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})
    monkeypatch.setattr(extensions, "current_username", lambda: "")
    monkeypatch.setattr(extensions, "current_email", lambda: "")

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    await registry.call("reference__echo", {"text": "hi"})

    assert session.metas == [None]
```

If `ExtensionStatus` has no `__repr__` that could include config values, the `"s3cret" not in repr(status)` check passes trivially; it guards against a future change that adds the config to the status.

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv_mcp\Scripts\python -m pytest tests/test_extensions.py -q -k "headers or requester or identity"`
Expected: FAIL: `seen` shows no `headers` key, and `session.metas == [None]` where a requester was expected.

- [ ] **Step 5: Write the implementation**

In `mcp_server/src/services/extensions.py`, change the identity import (line ~97):

```python
from src.services.identity_context import REQUESTER_META_KEY, current_email, current_username
```

In `_open_and_list`, change the http branch call:

```python
            read_stream, write_stream, _get_session_id = await local_stack.enter_async_context(
                streamablehttp_client(config.url, headers=config.headers or None)
            )
```

Replace the body of `call` after the `session = ...` line:

```python
        session = self._sessions[proxied.extension_id]
        return await session.call_tool(
            proxied.upstream_name,
            arguments,
            read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_SECONDS),
            meta=_requester_meta(),
        )
```

Add this module-level helper just above `class ExtensionRegistry`:

```python
def _requester_meta() -> dict[str, Any] | None:
    """The asking user, in the same ``_meta.requester`` shape ai_agent sends
    this server (see identity_context.py), so an upstream extension can tell
    users apart - e.g. pdf_merger keeps one file session per user. None when
    the caller sent no identity, so upstreams see exactly what they saw
    before this existed."""
    username, email = current_username(), current_email()
    if not (username or email):
        return None
    return {REQUESTER_META_KEY: {"username": username, "email": email}}
```

Extend `call`'s docstring with one paragraph:

```python
        The caller's identity (headers or ai_agent's ``_meta``, whichever
        this request carried) goes upstream as ``_meta.requester``. An
        upstream can only trust it as far as it trusts this server, which is
        why an http extension can be given the internal token in ``headers``.
```

- [ ] **Step 6: Run the whole mcp_server suite**

Run: `.venv_mcp\Scripts\python -m pytest -q`
Expected: PASS, including `test_real_fixture_server_end_to_end` (the real stdio fixture ignores `_meta`).

- [ ] **Step 7: Commit**

```bash
git add mcp_server/src/services/extensions.py mcp_server/tests/test_extensions.py
git commit -m "feat(mcp_server): send extension headers and forward requester to extensions"
```

---

### Task 3: Wire pdf_merger into mcp_server, the launcher and the vault

Needs plans 1 and 2 done.

**Files:**
- Modify: `mcp_server/configs/config_extensions.json.example` (tracked) and `mcp_server/configs/config_extensions.json` (local, gitignored by the repo-wide `config_*.json` rule)
- Modify: `server_launcher/data/groups.json`
- Modify (via the project-sync skill): `Brain/Projects/MCPServer.md`; create `Brain/Projects/pdf_merger.md`, `Brain/Projects/pdf_merger_web.md`

- [ ] **Step 1: Add the extension entry**

Add this entry to both `mcp_server/configs/config_extensions.json.example` and the local `mcp_server/configs/config_extensions.json` (keep the existing entries):

```json
  "pdf_merger": {
    "_comment": "pdf_merger's MCP endpoint (Python/MCPServer/pdf_merger). It requires the shared internal token, sent here as a header. Start pdf_merger before mcp_server so the connection succeeds at startup.",
    "label": "PDF Merger",
    "description": "Merge PDFs and images into one PDF by file ID; returns a download link.",
    "url": "http://127.0.0.1:8040/mcp",
    "headers": { "X-Internal-Token": "${INTERNAL_API_TOKEN}" }
  }
```

`INTERNAL_API_TOKEN` already reaches the environment: `mcp_server/src/run.py` loads every `.secrets/*.env` with `load_dotenv` before configs are read. The same value must be in `pdf_merger/.secrets/secret_internal_api.env`.

- [ ] **Step 2: Add launcher groups**

In `server_launcher/data/groups.json`, add a new top-level group:

```json
  "PDF Merger": {
    "members": [
      { "template_key": "pdf_merger", "port": 8040, "extra_env": {}, "extra_args": "", "preset_name": null },
      { "template_key": "pdf_merger_web", "port": 5174, "extra_env": {}, "extra_args": "", "preset_name": null }
    ]
  }
```

and append pdf_merger to the existing `"Ember"` group's `members` list, so Ember sessions have the tools:

```json
      { "template_key": "pdf_merger", "port": 8040, "extra_env": {}, "extra_args": "", "preset_name": null }
```

Check: open `server_launcher` (`server_launcher/run.bat`). Expected: "PDF Merger" and "PDF Merger Web" appear as templates (discovered from each `run.bat`'s `LABEL`), and the "PDF Merger" group lists both.

- [ ] **Step 3: End-to-end check**

1. Start in this order: `pdf_merger`, `mcp_server`, `ai_agent`, `ember_api`, `ember_web`, `pdf_merger_web`.
2. `mcp_server`'s banner lists `pdf_merger (connected)` under Extensions and tools `pdf_merger__tool_pdf_inspect`, `pdf_merger__tool_pdf_merge`, `pdf_merger__tool_pdf_listFiles`.
3. In `pdf_merger_web`, upload two PDFs and copy both IDs.
4. In Ember chat: "Merge <id1> pages 1-2 and all of <id2> into one PDF called test.pdf". Expected: the trace shows "Inspecting files" and "Merging files"; the answer has a download link that opens the merged PDF.
5. In `pdf_merger/.logs/server.log` or by calling `tool_pdf_listFiles` from chat: the result belongs to `mcp:<your Ember username>`, not `mcp:anonymous`.
6. Upload a `.docx` in `pdf_merger_web`. Expected: "This file type isn't supported…" (success criterion from the spec).

- [ ] **Step 4: Commit the tracked wiring**

```bash
git add mcp_server/configs/config_extensions.json.example server_launcher/data/groups.json
git commit -m "chore: wire pdf_merger into mcp_server extensions and server_launcher"
```

- [ ] **Step 5: Sync the vault**

Invoke the `project-sync` skill for MCPServer. It should:
- add `pdf_merger` (port 8040) and `pdf_merger_web` (port 5174) to the Components table, Ports line and Architecture diagram of `Brain/Projects/MCPServer.md`;
- add component notes `Brain/Projects/pdf_merger.md` and `Brain/Projects/pdf_merger_web.md`;
- list the PDF merger deferred items from `_TODO.md` under "Deferred work".

The vault has its own rules in `Brain/CLAUDE.md`; follow them. Vault commits are handled by the vault's hooks, not this repo.

---

## Self-review notes

- Spec "Integration" coverage: extension entry with `url` (Task 3), `headers` with `${ENV}` expansion (Tasks 1–3), requester forwarding as `_meta.requester` (Task 2), launcher group (Task 3), Ember download cards use the signed link from plan 1 (checked in Task 3 Step 3), vault sync (Task 3 Step 5).
- Type consistency: `ExtensionConfig.headers: dict[str, str]` (Task 1) is what `_open_and_list` reads (Task 2) and what tests construct through `_config(..., headers=...)`.

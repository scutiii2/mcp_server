# src/resources/

One folder per MCP resource - a client-readable URI (`scheme://...`),
for a caller that already knows what it wants and just needs to read
it, as opposed to a capability's tool (`src/capabilities/README.md`),
which a model calls by choosing among several. `host_health/` is the
one existing resource - see its own README for what it does.

## Shape of a resource

Same three-file split as a capability, minus `tool.py`:

- **`contract.py`** - Pydantic result models.
- **`domain.py`** - the real logic. Typed in, typed out, imports only
  `infra/` (never `mcp`). Unit-tested directly.
- **`resource.py`** - a few lines: load config, call the domain
  function, return text (or structured content). `@mcp.resource(...)`
  appears here and nowhere else.

`host_health/resource.py` is the worked example:

```python
@mcp.resource("host://health/{name}")
def host_health(name: str) -> str:
    config = load_host_config(settings.hosts_config_path, name)
    return format_report(collect(config))
```

## Add a new resource

1. `mkdir resources/<name>/` with an `__init__.py`.
2. `resources/<name>/contract.py`.
3. `resources/<name>/domain.py`.
4. `resources/<name>/resource.py`, decorated with `@mcp.resource("<scheme>://...")`.
5. In `imports.py`, add the import. If a capability toggle already governs
   this resource (see below), add it inside that capability's existing
   `capability_registry.capturing(mcp, "<name>")` block; otherwise wrap
   it in its own `capturing(mcp, "<name>")` block so it gets its own
   independent toggle.

## If a capability wraps this resource

`host_health` is both a resource (`resources/host_health/`, for a
client reading `host://health/{name}` directly) and a capability
(`capabilities/host_health/`, for a model calling `get_host_health_tool`)
- same domain logic underneath, reached two different ways. When that
split makes sense for a new resource too:

- The **resource** owns the logic (`domain.py`, `contract.py`). It has
  no dependency on the capability.
- The **capability** imports the resource's `domain`/`contract`
  modules and wraps them in a `tool.py` - see
  `capabilities/host_health/domain.py`'s docstring for why the
  dependency points this direction (deleting the capability wrapper
  should leave the resource fully working).
- One toggle entry in `../configs/config_capabilities.json` governs
  both - `imports.py` imports the resource and the capability's tool inside
  the *same* `capability_registry.capturing(mcp, "<name>")` block, so
  toggling `<name>` off/on live (via `PATCH /capabilities/<name>`,
  chat_app's Capabilities page) removes/restores both together.

A resource with no model-facing use doesn't need a matching capability
at all - it's a normal, independently-`capturing()`-wrapped import in
`run.py`, toggleable on its own.

# src/resources/

One folder per MCP resource - a client-readable URI (`scheme://...`),
for a caller that already knows what it wants and just needs to read
it, as opposed to a capability's tool (`src/capabilities/README.md`),
which a model calls by choosing among several. No resource exists in
this checkout today (an earlier `host_health/` resource this file used
to reference is gone) - the shape below is the pattern to follow the
first time one's needed, not a description of an existing file.

## Shape of a resource

Same three-file split as a capability, minus `tool.py`:

- **`contract.py`** - Pydantic result models.
- **`domain.py`** - the real logic. Typed in, typed out, imports only
  `services/` (never `mcp`). Unit-tested directly.
- **`resource.py`** - a few lines: load config, call the domain
  function, return text (or structured content). `@mcp.resource(...)`
  appears here and nowhere else.

Illustrative shape (not a real file in this checkout - there's no
resource to point at yet):

```python
@mcp.resource("example://widget/{name}")
def widget(name: str) -> str:
    config = load_widget_config(settings.widgets_config_path, name)
    return format_report(collect(config))
```

## Add a new resource

1. `mkdir resources/<name>/` with an `__init__.py`.
2. `resources/<name>/contract.py`.
3. `resources/<name>/domain.py`.
4. `resources/<name>/resource.py`, decorated with `@mcp.resource("<scheme>://...")`.
5. In `run.py`, add the import. If a capability toggle already governs
   this resource (see below), add it inside that capability's existing
   `capability_registry.capturing(mcp, "<name>")` block; otherwise wrap
   it in its own `capturing(mcp, "<name>")` block so it gets its own
   independent toggle.

## If a capability wraps this resource

No resource/capability pair like this exists in the current checkout to
point at as a worked example (an earlier `host_health` used to be one -
both a resource, for a client reading `host://health/{name}` directly,
and a capability, for a model calling a tool - same domain logic
underneath, reached two different ways). The pattern, for whenever a
resource needs a model-facing tool wrapper too:

- The **resource** owns the logic (`domain.py`, `contract.py`). It has
  no dependency on the capability.
- The **capability** imports the resource's `domain`/`contract`
  modules and wraps them in a `tool.py` - never the other direction, so
  deleting the capability wrapper leaves the resource fully working.
- One toggle entry in `../../configs/config_capabilities.json` governs
  both - `run.py` imports the resource and the capability's tool inside
  the *same* `capability_registry.capturing(mcp, "<name>")` block, so
  toggling `<name>` off/on live (via `PATCH /capabilities/<name>`,
  chat_app's Capabilities page) removes/restores both together.

A resource with no model-facing use doesn't need a matching capability
at all - it's a normal, independently-`capturing()`-wrapped import in
`run.py`, toggleable on its own.

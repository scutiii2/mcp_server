# Capabilities

Live browser for the MCP server's tool and resource catalog, grouped by
extension and by capability label, with a "try it" console that invokes
a tool or reads a resource directly (bypassing chat). Ported from
MCPArchitecture - see
`docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md`.

Two permissions: `capabilities.view` gates the page and its read-only
`/api/tools`/`/api/resources`; `capabilities.try` separately gates
`/api/try/<tool_name>` and `/api/read-resource`, since those actually
invoke real MCP tools with caller-supplied arguments. `PAGE_PERMISSION`
is a tuple of both - visible in `nav_pages` to an account holding
either one, same pattern as the Logs page. `CSRF_EXEMPT = True`: see
Chat's README for why.

A "Run"/"Read" result shows the same Markdown rendering as a chat "/"
command reply, not the tool's raw JSON - `try_tool()`/`read_resource_route()`
run the result through `services/command_formatting.py`'s
`format_command_result()` (see `../../../../mcp_server/src/capabilities/README.md`'s
"Output formatting" section for the contract-shape convention this
depends on) and return both `formatted` and the untouched `result` text;
`result_panel.html`/`script.js` render `formatted` by default with a
"Show raw JSON" toggle underneath for the wire response.

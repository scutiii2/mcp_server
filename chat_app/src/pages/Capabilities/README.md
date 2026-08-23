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

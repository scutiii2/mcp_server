# capabilities/usage_report/

Add up token usage per agent, model or day from ai_agent's usage log - one tool.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_usage_summary` | Token usage per agent, model or day. | Local usage log |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_usage_summary` | `/usage summary` | <ul><li>`days` - optional, default `7`. How many days back, today included (1 to 90).</li><li>`group_by` - optional, default `agent`. `agent`, `model` or `day`.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_usage_summary` | Pick the period and what to group by. |

## Configuration

`MCP_USAGE_DIR` in `.env`: the folder holding ai_agent's `YYYY-MM-DD.<agent id>.jsonl` files. Default
`../ai_agent/data/usage`, relative to `apps/mcp_server/`. Read-only. The date in the file name picks the files to
read. A line that is not valid JSON is counted in `skipped_lines`. Tokens only: the log has no prices. This is
the agents' own log; ember_api's per-account usage and limits are separate.

Toggle: `"usage"` in `configs/config_capabilities.json`.

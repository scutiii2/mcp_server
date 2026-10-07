# capabilities/web_research/

Search the web and read a page's text through [Tavily](https://tavily.com) - two tools.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_web_search` | Search the web; returns titles, addresses and snippets. | Tavily API |
| `tool_web_readPage` | Read the text of one web page. | Tavily API |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_web_search` | `/web search` | <ul><li>`query` - required. What to search for.</li><li>`max_results` - optional, default `5`. How many results (1 to 10).</li><li>`topic` - optional, default `general`. `news` for recent events.</li></ul> |
| `tool_web_readPage` | `/web read` | <ul><li>`url` - required. Full http:// or https:// address.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_web_search` | Find candidate pages. |
| 2 | `tool_web_readPage` | Read the best one or two pages, then answer and cite their addresses. |

## Configuration

`TAVILY_API_KEY` in `apps/mcp_server/.env` (key from https://app.tavily.com). Without it each tool fails with a
message naming the variable; the rest of the server is unaffected. The client is built per call.

Tavily fetches the pages, so this server never connects to an address a caller chose. Page text is capped at
24 KB and fenced as remote data (`services/untrusted.py`); search snippets are cut to 600 characters. Tavily's
own generated answer is not requested: tools never call an AI. Each search and each page read uses Tavily credits.

Toggle: `"web"` in `configs/config_capabilities.json`.

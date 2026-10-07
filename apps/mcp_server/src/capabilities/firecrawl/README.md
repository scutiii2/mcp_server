# capabilities/firecrawl/

Scrape a web page, list a site's pages and crawl a site through [Firecrawl](https://www.firecrawl.dev) - three tools. It calls the Firecrawl REST API, the same endpoints the official [firecrawl-mcp-server](https://github.com/firecrawl/firecrawl-mcp-server) wraps.

## Tools

| Tool | Purpose | Connection |
| --- | --- | --- |
| `tool_scrape_page` | Scrape one web page as markdown. | Firecrawl API |
| `tool_scrape_map` | List the pages found on a site. | Firecrawl API |
| `tool_scrape_crawl` | Crawl a site and return the text of its pages. | Firecrawl API |

## Slash commands

| Tool | Slash command | Parameters |
| --- | --- | --- |
| `tool_scrape_page` | `/scrape page` | <ul><li>`url` - required. Full http:// or https:// address.</li></ul> |
| `tool_scrape_map` | `/scrape map` | <ul><li>`url` - required. Full http:// or https:// address of the site or section.</li><li>`limit` - optional, default `100`. How many pages to list (1 to 500).</li></ul> |
| `tool_scrape_crawl` | `/scrape crawl` | <ul><li>`url` - required. Full http:// or https:// address where the crawl starts.</li><li>`limit` - optional, default `10`. How many pages to read (1 to 25).</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
| --- | --- | --- |
| 1 | `tool_scrape_map` | List a site's pages and pick the ones to read. |
| 2 | `tool_scrape_page` | Read each chosen page. |
| 3 | `tool_scrape_crawl` | Or crawl from a starting address when many pages are needed. |

## Configuration

`FIRECRAWL_API_KEY` in `apps/mcp_server/.env` (key from https://www.firecrawl.dev/app). Without it each tool fails with a
message naming the variable; the rest of the server is unaffected. `FIRECRAWL_API_URL` is optional: leave it blank for the
hosted API, or set it to a self-hosted instance (the key is then optional). The client is built per call.

Firecrawl fetches the pages, so this server never connects to an address a caller chose. Page text is capped at 24 KB
(a crawl at 48 KB in total) and fenced as remote data (`services/untrusted.py`). Tools never call an AI. Crawl waits up
to 60 seconds; if the job is still running the result says so and holds the pages read so far. Every page uses Firecrawl credits.

Not included: Firecrawl's search (use `/web search`) and its LLM-based extract.

Toggle: `"scrape"` in `configs/config_capabilities.json`.

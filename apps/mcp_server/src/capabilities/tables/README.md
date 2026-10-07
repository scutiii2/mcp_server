# capabilities/tables/

Read-only questions about a CSV or Excel file the user attached in Ember chat - seven tools, no code execution.
Chat id `data`, label "Data Tables".

## How a file gets here

`ember_web` uploads an attached `.csv` / `.xlsx` through `ember_api` to `POST /upload/table` (`upload_routes.py`,
internal token required). `services/table_loader.py` parses the whole file once into typed columns;
`services/tables.py` keeps it in memory under a random id, bound to the requesting account. Nothing is written to disk.
A restart, or 30 minutes, drops the table: attach the file again.

## Tools

| Tool | Purpose |
| --- | --- |
| `tool_tables_listTables` | The caller's tables with ids and minutes left. |
| `tool_tables_describe` | Per column: type, empty cells, distinct values, min / max / mean, common text values. |
| `tool_tables_head` | The first rows. |
| `tool_tables_filter` | Rows that satisfy up to 5 conditions (AND). |
| `tool_tables_aggregate` | sum / mean / count / min / max per group (up to 2 group columns), optional filter, sort, limit. |
| `tool_tables_topN` | Highest or lowest rows by a number or date column. |
| `tool_tables_valueCounts` | How often each value appears in a column. |

## Slash commands

`/data list`, `/data describe table_id=...`, `/data head table_id=... limit=10`,
`/data counts table_id=... column=... limit=20`. The filter, aggregate and top tools take structured arguments, so
they are for the agent only.

## Limits

30 minute TTL; 10 tables per account, 20 in total; 15 MB per file; 200,000 rows; 200 columns; 100 MB of stored
uploads in total. Results are capped at 50 rows or 100 groups, cell text at 200 characters.
Column types: number if at least 95% of the non-empty cells parse as numbers (`1,234.5` and `12%` do), else date if
at least 95% parse as ISO dates, else text. Cells that fail the type are left empty and reported in `notes`.
Empty cells never match a comparison; use `is_null` / `not_null`.

## Security

Every id is random, opaque and owner-bound; an unknown, expired or foreign id gives the same "not found". Cell values
come from the user's file and may hold injection text, so each result carries a `notice` saying they are data.

Toggle: `"data"` in `configs/config_capabilities.json`.

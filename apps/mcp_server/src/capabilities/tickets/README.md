# capabilities/tickets/
Report bugs and failures, suggest features, and follow your own support tickets with `/ticket`.
Tools: `tool_ticket_createTicket` (`create`), `tool_ticket_listMyTickets` (`list`), `tool_ticket_getTicket` (`show`), `tool_ticket_addComment` (`reply`).
The core store in `src/services/tickets.py` and HTTP routes in `src/ticket_routes.py` stay available when this capability is off; toggle the chat tools with `PATCH /capabilities/ticket`.
Staff triage is planned for Ember Admin via ember_api; configuration is `configs/config_tickets.json`, optional `LAYA_URL`, and `MCP_TICKETS_DB_PATH` for core SQLite storage.

The create form uses `input=tags` with `options_url=/tickets/tags` and a five-tag limit.
`GET /tickets/tags` returns the configured tag vocabulary and descriptions; it requires
the internal API token and requester identity and stays available when the capability is off.

Manual reports and staff edits accept custom tag names (up to 64 letters, numbers,
hyphens or underscores; spaces become hyphens). Tags are persisted on the ticket;
`/tickets/tags` also suggests custom tags from the requester's own tickets.
AI reports continue using the configured vocabulary.

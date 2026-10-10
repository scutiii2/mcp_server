# capabilities/tickets/
Report bugs and failures, suggest features, and follow your own support tickets with `/ticket`.
Tools: `tool_ticket_createTicket` (`create`), `tool_ticket_listMyTickets` (`list`), `tool_ticket_getTicket` (`show`), `tool_ticket_addComment` (`reply`).
The core store in `src/services/tickets.py` and HTTP routes in `src/ticket_routes.py` stay available when this capability is off; toggle the chat tools with `PATCH /capabilities/ticket`.
Staff triage is planned for Ember Admin via ember_api; configuration is `configs/config_tickets.json`, optional `LAYA_URL`, and `MCP_TICKETS_DB_PATH` for core SQLite storage.

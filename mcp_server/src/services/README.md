# src/services/

Business logic that coordinates more than one `infra/` client or spans
more than one capability - mirrors chat_app/src/services/'s role in
that project, where route handlers stay thin and logic that makes a
policy decision lives here instead.

Empty for now. `infra/` already holds this server's thin clients (SSH,
email, the JSON config loader, the pending-requests store) and each
`capabilities/<name>/domain.py` holds that one capability's own logic -
neither is the right home for something that needs both, or that no
single capability owns. `infra/approvals.py` (the human-approval gate,
used by more than one capability) is the closest existing candidate for
what belongs here; it stays under `infra/` for now rather than being
moved speculatively.

Add a module here when a piece of logic outgrows a single capability's
`domain.py` or a single `infra/` client - not before.

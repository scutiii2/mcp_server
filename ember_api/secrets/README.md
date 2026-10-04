# secrets

Real `secret_*.env` files are gitignored; each has a committed `.example`
twin that is copied on first run if the real file is missing.

- `secret_bootstrap_admin.env` - username/email/password of the first
  admin account (see the example file).
- `secret_smtp.env` - SMTP account for invite and verification emails.
  Without it, registration still works but codes can't be emailed.
- `secret_internal_api.env` - optional `INTERNAL_API_TOKEN` sent to ai_agent
  and mcp_server on proxied requests.

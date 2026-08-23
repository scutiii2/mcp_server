# capabilities/otp/

Emails a one-time passcode to a configured address and verifies it back
- `request_otp_tool` / `verify_otp_tool`. The code is never returned to
the caller; only whoever reads the inbox can complete the check. See
`domain.py`'s docstring for why that's the entire point of the
mechanism.

**Reads:** `../../../configs/config_email.json` (recipient allowlist,
domains, SMTP settings) and, through `infra/email.py`,
`../../../secrets/secret_smtp.env` (`SMTP_PASSWORD`) - both shared with
`infra/approvals.py`, not owned by this capability alone.

**Owns:** `data/otp.db` - `infra/otp.py`'s salted-hash store of issued
codes. Created automatically on first use; nothing else reads or writes
it (contrast `../../../data/README.md`'s `pending_requests.db`, which
several capabilities could share). Not committed - regenerable, and
holds nothing worth keeping between runs (codes expire in minutes).

**Toggle:** `"otp"` in `../../../configs/config_capabilities.json`.

"""Server-wide settings.

Deliberately plain (no external settings library required) - swap for
pydantic-settings later if the number of tunables grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    config_path: Path = Path(os.getenv("CONFIG_PATH", "config.json"))
    host: str = os.getenv("MCP_HOST", "0.0.0.0")
    port: int = int(os.getenv("MCP_PORT", "8010"))
    # SQLite file backing infra/pending_requests.py - relative to CWD by
    # default (kept fragile-by-default rather than fixed only here).
    # Backs any approval-gated / resumable capability you add later, not
    # tied to any specific tool.
    pending_requests_path: Path = Path(os.getenv("PENDING_REQUESTS_PATH", "pending_requests.db"))
    # The URL an approval email's link would point at, for any future
    # approval-gated capability built on infra/pending_requests.py +
    # infra/email.py. Deliberately NOT derived from host/port above -
    # `host` is a bind address (0.0.0.0 is not a real client-reachable
    # hostname), while this needs to be whatever address actually
    # resolves from an approver's inbox (a VPN hostname, a
    # reverse-proxy address, etc). Defaults to localhost so this at
    # least works out of the box for local testing; override for any
    # real deployment.
    public_base_url: str = os.getenv("MCP_PUBLIC_BASE_URL", "http://127.0.0.1:8010")


settings = Settings()
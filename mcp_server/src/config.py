"""Server-wide settings.

Deliberately plain (no external settings library required) - swap for
pydantic-settings later if the number of tunables grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    """os.getenv, but an empty value counts as unset.

    ``os.getenv`` returns "" for a variable that's present but blank, so a
    commented-out-by-emptying line in .env (``SSH_KNOWN_HOSTS=``) would
    override the default with an empty string rather than leave it alone -
    which for a path means Path(""), i.e. the current directory. Blank
    almost always means "I didn't set this".
    """
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    # Where the four config_*.json files (see infra/app_config.py) live.
    # Relative to CWD by default, same fragile-by-default convention as
    # every path below - mcp_server is always run from its own directory
    # (run_mcp_server.bat cd's there first), so "src/configs" resolves.
    configs_dir: Path = Path(_env("MCP_CONFIGS_DIR", "src/configs"))
    # Loopback by default, deliberately. This server has no authentication
    # of its own: anything that can reach the port can call every
    # registered tool with arbitrary arguments, and the Flask app is not
    # in that path, so no amount of auth over there protects this. Binding
    # to 0.0.0.0 exposes that to the whole network, which should be a
    # decision someone makes on purpose rather than a default they
    # inherit. Override MCP_HOST only once something in front of it
    # (reverse proxy, VPN, firewall) is doing the authenticating.
    host: str = _env("MCP_HOST", "127.0.0.1")
    port: int = int(_env("MCP_PORT", "8010"))
    # SQLite file backing infra/pending_requests.py - relative to CWD by
    # default (kept fragile-by-default rather than fixed only here).
    # Backs any approval-gated / resumable capability, not tied to any
    # specific one, so it lives under the general src/data/ rather than
    # inside any single capabilities/<name>/ folder.
    pending_requests_path: Path = Path(_env("PENDING_REQUESTS_PATH", "src/data/pending_requests.db"))
    # SQLite file backing infra/otp.py - relative to CWD by default, same
    # as pending_requests_path above. Defaults inside capabilities/otp/,
    # the one capability that owns this file - unlike
    # pending_requests_path, nothing else ever reads or writes it. Only
    # the path is a setting: code length, TTL and the attempt limit stay
    # constants in infra/otp.py, because they are what makes a six-digit
    # secret safe and an env var is too easy a place to weaken them from.
    otp_path: Path = Path(
        _env("OTP_PATH", "src/capabilities/otp/data/otp.db")
    )
    # The URL an approval email's link points at. Deliberately NOT derived
    # from host/port above - `host` is a bind address (127.0.0.1 and
    # 0.0.0.0 are both meaningless from someone else's inbox), while this
    # needs to be whatever address actually resolves for an approver (a
    # VPN hostname, a reverse-proxy address, etc). Defaults to localhost
    # so this works out of the box for local testing; override for any
    # real deployment.
    public_base_url: str = _env("MCP_PUBLIC_BASE_URL", "http://127.0.0.1:8010")
    # known_hosts file used to verify SSH host keys. Defaults to the same
    # one the ssh command-line client uses, so hosts you've already
    # connected to from this machine are trusted without extra setup.
    ssh_known_hosts: Path = Path(
        _env("SSH_KNOWN_HOSTS", str(Path.home() / ".ssh" / "known_hosts"))
    )
    # "reject" (default) or "auto". Rejecting an unknown host key is the
    # point of having known_hosts at all: it's what makes a
    # machine-in-the-middle visible, and - more importantly in practice -
    # what makes a host key that *changed* an error instead of a silent
    # accept. "auto" trusts whatever key answers first and records it,
    # which is fine for a throwaway lab and wrong everywhere else.
    ssh_host_key_policy: str = _env("SSH_HOST_KEY_POLICY", "reject")
    # Where logging_setup.configure_logging() writes server.log and
    # errors.report() writes per-reference error files. Relative to CWD by
    # default, same convention as the paths above.
    log_dir: Path = Path(_env("MCP_LOG_DIR", "src/logs"))

    @property
    def hosts_config_path(self) -> Path:
        return self.configs_dir / "config_hosts.json"

    @property
    def email_config_path(self) -> Path:
        return self.configs_dir / "config_email.json"

    @property
    def extensions_config_path(self) -> Path:
        return self.configs_dir / "config_extensions.json"

    @property
    def capabilities_config_path(self) -> Path:
        return self.configs_dir / "config_capabilities.json"


settings = Settings()

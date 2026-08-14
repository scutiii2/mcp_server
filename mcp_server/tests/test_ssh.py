"""Tests for infra/ssh.py's security-relevant behavior.

No network and no SSH server: these cover the two things that are pure
logic - how a command gets quoted before it reaches a remote shell, and
how the paramiko client is configured before it connects.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import paramiko
import pytest

from mcp_server.infra.ssh import SSHClient, _new_client


# --- shell quoting -----------------------------------------------------
# run_login_shell() embeds a command inside `/bin/bash -lc ...`. Tool
# arguments here come from an LLM that may be reading attacker-controlled
# text, so "the caller will pass something sane" is not an assumption
# available to us.


def _wrapped(command: str, shell: str = "bash") -> str:
    """Capture what run_login_shell() would actually execute."""
    client = SSHClient("host", "user", password="pw")
    client._client = MagicMock()
    captured: dict[str, str] = {}

    def fake_run(cmd: str):
        captured["cmd"] = cmd
        return MagicMock()

    client.run = fake_run  # type: ignore[method-assign]
    client.run_login_shell(command, shell=shell)
    return captured["cmd"]


def test_plain_command_is_wrapped_in_a_login_shell():
    assert _wrapped("uptime") == "/bin/bash -lc uptime"


def test_csh_variant_uses_csh():
    assert _wrapped("uptime", shell="csh") == "/bin/csh -c uptime"


@pytest.mark.parametrize(
    "payload",
    [
        'uptime"; rm -rf /tmp/x; echo "',   # closes the old double quote
        "uptime $(rm -rf /tmp/x)",           # command substitution
        "uptime `rm -rf /tmp/x`",            # backtick substitution
        "uptime && rm -rf /tmp/x",           # operator chaining
        "uptime; rm -rf /tmp/x",             # statement separator
        "uptime\nrm -rf /tmp/x",             # newline as separator
    ],
)
def test_injection_payloads_stay_a_single_argument(payload):
    """Each of these used to break out of the old f'...\"{command}\"'
    wrapper. Quoted, the whole payload is one argument to -c, so the
    remote shell runs it as a (failing) command name rather than as
    several commands."""
    wrapped = _wrapped(payload)

    assert wrapped.startswith("/bin/bash -lc '")
    assert wrapped.endswith("'")
    # The dangerous text survives verbatim inside the quotes - it just
    # isn't shell syntax any more.
    inner = wrapped[len("/bin/bash -lc ") :]
    assert "rm -rf /tmp/x" in inner


def test_embedded_single_quote_is_escaped_not_dropped():
    wrapped = _wrapped("echo 'hi'")

    assert "'\"'\"'" in wrapped  # shlex's standard escape for a quote


# --- host key policy ---------------------------------------------------


def test_unknown_host_keys_are_rejected_by_default(tmp_path: Path):
    known = tmp_path / "known_hosts"
    known.touch()

    client = _new_client(known_hosts=known)

    assert isinstance(client._policy, paramiko.RejectPolicy)


def test_auto_policy_is_opt_in(tmp_path: Path):
    client = _new_client(known_hosts=tmp_path / "known_hosts", host_key_policy="auto")

    assert isinstance(client._policy, paramiko.AutoAddPolicy)


def test_auto_policy_creates_the_file_so_accepted_keys_persist(tmp_path: Path):
    """AutoAdd only writes keys back if the client knows which file to use,
    and paramiko only learns that from load_host_keys() - which raises on
    a missing file. Without this, trust-on-first-use would re-trust on
    every connection and never actually record anything."""
    known = tmp_path / "nested" / "known_hosts"

    client = _new_client(known_hosts=known, host_key_policy="auto")

    assert known.exists()
    assert client._host_keys_filename == str(known)


def test_existing_known_hosts_entries_are_loaded(tmp_path: Path):
    known = tmp_path / "known_hosts"
    key = paramiko.RSAKey.generate(2048)
    known.write_text(f"example.com {key.get_name()} {key.get_base64()}\n", encoding="utf-8")

    client = _new_client(known_hosts=known)

    assert "example.com" in client.get_host_keys()


def test_missing_known_hosts_under_reject_policy_is_not_an_error(tmp_path: Path):
    """A missing file means "nothing is trusted yet", which the reject
    policy handles correctly on its own. Creating it here would be
    pointless since reject never writes to it."""
    known = tmp_path / "does-not-exist"

    client = _new_client(known_hosts=known)

    assert not known.exists()
    assert isinstance(client._policy, paramiko.RejectPolicy)


def test_unknown_policy_name_fails_loudly(tmp_path: Path):
    """A typo in SSH_HOST_KEY_POLICY must not quietly fall back to
    something permissive."""
    with pytest.raises(ValueError, match="expected 'reject' or 'auto'"):
        _new_client(known_hosts=tmp_path / "known_hosts", host_key_policy="ignore")


# --- port ---------------------------------------------------------------


def test_configured_port_reaches_paramiko(tmp_path: Path):
    """Regression: `port` was accepted in config.json, defaulted to 22, and
    then dropped - SSHClient had no port parameter at all, so a host on a
    non-standard sshd port silently connected to 22. Config that is
    accepted and ignored is worse than config that is rejected."""
    known = tmp_path / "known_hosts"
    known.touch()
    client = SSHClient("h", "u", password="pw", port=2222, known_hosts=known)
    client._client = MagicMock()

    client._connect()

    assert client._client.connect.call_args.kwargs["port"] == 2222


def test_port_defaults_to_22(tmp_path: Path):
    known = tmp_path / "known_hosts"
    known.touch()
    client = SSHClient("h", "u", password="pw", known_hosts=known)
    client._client = MagicMock()

    client._connect()

    assert client._client.connect.call_args.kwargs["port"] == 22

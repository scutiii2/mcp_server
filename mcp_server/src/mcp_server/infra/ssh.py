"""One SSH client for the whole server.

Every capability that needs a remote shell goes through this module, so
connection handling, auth-fallback order, host-key verification, and
timeout behavior are identical everywhere and tested once. Resist adding
a second paramiko-connecting code path elsewhere - that's how you end up
with three implementations that each retry slightly differently and only
two of which check host keys.

**Host keys are verified.** Unknown ones are rejected, against
``settings.ssh_known_hosts`` (your normal ``~/.ssh/known_hosts`` by
default, so hosts you've already reached from this machine just work).
The reason this matters isn't really first-contact interception, it's the
second connection onward: with verification off, a host key that
*changed* - the actual signal that something is wrong - is accepted in
silence. Set ``SSH_HOST_KEY_POLICY=auto`` to trust-on-first-use instead;
it records what it accepts, so a lab machine can be enrolled that way and
then switched back to rejecting.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import paramiko

from mcp_server.config import settings


def _new_client(
    *,
    known_hosts: Path | str | None = None,
    host_key_policy: str | None = None,
) -> paramiko.SSHClient:
    """A paramiko client with host-key verification already set up.

    Every connect path in this module goes through here - the point is
    that there's nowhere left to accidentally omit the policy.
    """
    policy_name = (host_key_policy or settings.ssh_host_key_policy).strip().lower()
    if policy_name not in {"reject", "auto"}:
        raise ValueError(
            f"Unknown SSH_HOST_KEY_POLICY {policy_name!r} - expected 'reject' or 'auto'."
        )

    path = Path(known_hosts) if known_hosts is not None else settings.ssh_known_hosts
    client = paramiko.SSHClient()

    if policy_name == "auto" and not path.exists():
        # Create it so paramiko has somewhere to persist what it accepts -
        # load_host_keys() is what tells the client which file to write
        # back to, and it raises if the file is missing.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    if path.exists():
        client.load_host_keys(str(path))

    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy() if policy_name == "auto" else paramiko.RejectPolicy()
    )
    return client


@dataclass
class SSHCommandResult:
    stdout: str
    stderr: str
    exit_status: int

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class SSHClient:
    """Context-manager SSH connection with key-then-password auth fallback.

    Usage:
        with SSHClient(host, user, key=key_path, password=password) as ssh:
            result = ssh.run("systemctl status nginx")
    """

    def __init__(
        self,
        host: str,
        user: str,
        *,
        key: str | None = None,
        password: str | None = None,
        port: int = 22,
        connect_timeout: int = 10,
        command_timeout: int = 30,
        known_hosts: Path | str | None = None,
        host_key_policy: str | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.key = key
        self.password = password
        self.port = port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.known_hosts = known_hosts
        self.host_key_policy = host_key_policy
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> "SSHClient":
        self._client = _new_client(
            known_hosts=self.known_hosts, host_key_policy=self.host_key_policy
        )
        self._connect()
        return self

    def _connect(self) -> None:
        assert self._client is not None
        last_error: Exception | None = None

        if self.key:
            try:
                self._client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.user,
                    key_filename=self.key,
                    timeout=self.connect_timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
                return
            except Exception as error:  # noqa: BLE001 - fall through to password
                last_error = error

        if self.password:
            try:
                self._client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.user,
                    password=self.password,
                    timeout=self.connect_timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
                return
            except Exception as error:  # noqa: BLE001
                last_error = error

        # Deliberately not just "auth failed": with host-key verification
        # on, the most likely first-run failure is an unknown host key,
        # and calling that an auth problem sends you off checking
        # passwords for no reason.
        hint = ""
        if isinstance(last_error, paramiko.SSHException) and "known_hosts" in str(last_error):
            hint = (
                f" The host key for {self.host} is not in "
                f"{self.known_hosts or settings.ssh_known_hosts}. Add it "
                f"(ssh-keyscan, or connect once with the ssh client), or set "
                f"SSH_HOST_KEY_POLICY=auto to trust on first use."
            )
        raise ConnectionError(
            f"SSH connection to {self.user}@{self.host} failed: {last_error}.{hint}"
        )

    def run(self, command: str) -> SSHCommandResult:
        assert self._client is not None, "SSHClient must be used as a context manager"
        _stdin, stdout, stderr = self._client.exec_command(command, timeout=self.command_timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return SSHCommandResult(stdout=out, stderr=err, exit_status=code)

    def run_login_shell(self, command: str, shell: str = "bash") -> SSHCommandResult:
        """Run a command through an actual login shell, not a bare
        exec_command(). A raw exec_command() doesn't source any profile,
        so an unqualified command fails with "command not found" whenever
        the target binary is only on PATH because the user's shell rc
        file put it there - common for service accounts that ship their
        own environment setup.

        ``shell`` picks which login shell to wrap with, since that isn't
        guessable from the username: pass "csh" for accounts whose
        environment lives in .cshrc, "bash" (the default) otherwise.
        Domain code knows which kind of account it's connecting as; this
        method deliberately doesn't try to infer it.

        ``command`` is shell-quoted before being embedded. The previous
        version interpolated it into a double-quoted string, where
        ``$(...)``, backticks, ``\\`` and ``"`` all escape the wrapper and
        run as separate commands. That is reachable input, not theoretical:
        tool arguments here originate from an LLM, which may be
        summarizing a log file or a web page an attacker controls. Quoting
        makes the whole string one argument no matter what's in it."""
        quoted = shlex.quote(command)
        if shell == "csh":
            wrapped = f"/bin/csh -c {quoted}"
        else:
            wrapped = f"/bin/bash -lc {quoted}"
        return self.run(wrapped)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            self._client.close()


def run_command(
    host: str,
    user: str,
    *,
    key: str | None = None,
    password: str | None = None,
    command: str,
    timeout: int = 30,
) -> tuple[bool, str, str]:
    """Bare exec_command (no login-shell wrapping), returning
    (connected, stdout, stderr) - a one-shot convenience wrapper for
    domain code that doesn't need to hold a connection open.

    "connected" reflects whether the SSH connection and command execution
    completed without raising. It does NOT check the remote command's own
    exit code, so a command that ran but printed only to stderr still
    reports connected=True with the text in stderr rather than stdout. Use
    ``SSHClient`` directly if you need the exit status.

    Distinct from ``SSHClient.run_login_shell()``, which wraps the command
    in an actual login shell. Prefer this one by default - it's cheaper
    and quotes nothing - and switch to ``run_login_shell()`` at the
    specific call site where a command turns out to need the profile
    sourced to be found on PATH.
    """
    try:
        with SSHClient(host, user, key=key, password=password, command_timeout=timeout) as ssh:
            result = ssh.run(command)
            return True, result.stdout, result.stderr
    except ConnectionError as error:
        return False, "", str(error)


def sftp_upload_dir(host: str, user: str, password: str, local_dir: str, remote_dir: str) -> int:
    """Recursively upload local_dir's contents into remote_dir over SFTP,
    password auth. Returns the number of files uploaded.

    Opens its own one-off connection rather than reusing ``SSHClient``,
    which is exec-focused and never opens an SFTP channel. Note this
    means the local machine running the MCP server needs the files
    already staged on its own filesystem - a capability built on this is
    tied to wherever this process runs, unlike one that only needs
    network reach to the remote host.
    """
    import os

    client = _new_client()
    client.connect(hostname=host, username=user, password=password, timeout=15, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    try:
        def _mkdir_p(path: str) -> None:
            path = path.rstrip("/") or "/"
            try:
                sftp.stat(path)
            except FileNotFoundError:
                parent = path.rsplit("/", 1)[0] or "/"
                if parent != path:
                    _mkdir_p(parent)
                sftp.mkdir(path)

        uploaded = 0
        for root, _dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir).replace("\\", "/")
            remote_root = remote_dir if rel == "." else f"{remote_dir}/{rel}"
            _mkdir_p(remote_root)
            for fname in files:
                local_path = os.path.join(root, fname)
                remote_path = f"{remote_root}/{fname}"
                sftp.put(local_path, remote_path)
                uploaded += 1
        return uploaded
    finally:
        sftp.close()
        client.close()


def sftp_write_file(host: str, user: str, key: str | None, password: str | None, remote_path: str, content: str) -> None:
    """Write a single small text file to the remote host over SFTP -
    useful for staging a generated script before running it with
    ``SSHClient.run()``. Distinct from ``sftp_upload_dir`` above (which
    recursively uploads a whole local directory): this writes one string
    to one remote path, with no local file involved at all."""
    client = _new_client()
    try:
        if key:
            client.connect(hostname=host, username=user, key_filename=key, timeout=10, look_for_keys=False, allow_agent=False)
        else:
            client.connect(hostname=host, username=user, password=password, timeout=10, look_for_keys=False, allow_agent=False)
        sftp = client.open_sftp()
        with sftp.file(remote_path, "w") as f:
            f.write(content)
        sftp.close()
    finally:
        client.close()

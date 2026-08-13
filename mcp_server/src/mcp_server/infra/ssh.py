"""One SSH client for the whole server.

Every capability that needs a remote shell goes through this module, so
connection handling, auth-fallback order, and timeout behavior are
identical everywhere and tested once. Resist adding a second
paramiko-connecting code path elsewhere - that's how you end up with
three implementations that each retry slightly differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType

import paramiko


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
        connect_timeout: int = 10,
        command_timeout: int = 30,
    ) -> None:
        self.host = host
        self.user = user
        self.key = key
        self.password = password
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._client: paramiko.SSHClient | None = None

    def __enter__(self) -> "SSHClient":
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._connect()
        return self

    def _connect(self) -> None:
        assert self._client is not None
        last_error: Exception | None = None

        if self.key:
            try:
                self._client.connect(
                    hostname=self.host,
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
                    username=self.user,
                    password=self.password,
                    timeout=self.connect_timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
                return
            except Exception as error:  # noqa: BLE001
                last_error = error

        raise ConnectionError(
            f"SSH auth failed for {self.user}@{self.host}: {last_error}"
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
        method deliberately doesn't try to infer it."""
        if shell == "csh":
            wrapped = f'/bin/csh -c "{command}"'
        else:
            wrapped = f'/bin/bash -lc "{command}"'
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

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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

"""One SSH client for the whole server.

The legacy codebase had at least three separate SSH-connect implementations
(``_ssh`` in mcp_server.py, ``_ssh_connect_raw`` in sapren_bp.py, plus inline
paramiko calls in admin_bp.py) with slightly different auth-fallback order
and retry behavior in each. Centralizing it here means every domain function
gets identical, tested connection handling for free.
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
            result = ssh.run("systemctl status sapinit")
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
        so unqualified commands like `sapcontrol` fail with "command not
        found" for SAP admin users whose PATH is set up by their shell
        rc file. Classic SAP application-server admin users (sidadm, e.g.
        e4gadm) conventionally use /bin/csh for exactly this reason;
        HANA admins and general-purpose accounts use /bin/bash. Pass
        whichever is correct for the connecting user - domain code should
        know which tier (DB vs ASCS/PAS/AAS) it's targeting rather than
        this method trying to guess from the username."""
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
    (connected, stdout, stderr). Port of the legacy mcp_server.py's
    ``_ssh()`` helper, used throughout the monitoring tools.

    "connected" reflects whether the SSH connection+command execution
    completed without raising - it does NOT check the remote command's
    own exit code (the legacy function didn't either), so a command that
    ran but printed only to stderr still reports connected=True with the
    text in stderr rather than stdout.

    Distinct from ``SSHClient.run_login_shell()``: that wraps the command
    in an actual login shell, needed for sidadm users whose PATH depends
    on .cshrc/.profile (used by capabilities/control/). This runs the
    bare command directly, matching what the legacy monitoring tools
    actually did - it works because paramiko's exec_command on many SSH
    server configs still resolves enough PATH for sapcontrol to be found,
    even without full login-shell semantics. If a specific tool turns out
    to need login-shell wrapping in your environment, use
    ``SSHClient.run_login_shell()`` directly at that call site instead.
    """
    try:
        with SSHClient(host, user, key=key, password=password, command_timeout=timeout) as ssh:
            result = ssh.run(command)
            return True, result.stdout, result.stderr
    except ConnectionError as error:
        return False, "", str(error)


def sftp_upload_dir(host: str, user: str, password: str, local_dir: str, remote_dir: str) -> int:
    """Recursively upload local_dir's contents into remote_dir over SFTP,
    password auth. Faithful port of the legacy _sftp_upload_dir - one-off
    connection (not reusing SSHClient, since that's exec-focused and this
    needs an SFTP channel instead), used only by kernel updates to push
    extracted .SAR contents from the Windows machine running this server
    to the remote SAP host. Returns the number of files uploaded.
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

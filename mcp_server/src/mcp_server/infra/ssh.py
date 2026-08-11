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

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            self._client.close()

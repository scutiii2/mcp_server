"""Gather basic health facts from a host over SSH.

Two command sets, picked by the host's declared OS, because Linux and
Windows share essentially nothing here - not the commands, not the units,
not the shell that parses them.

**Linux** reads ``/proc`` rather than running ``top``/``free``/``uptime``.
Those are formatted for people: the layout shifts between distributions
and procps versions, and ``free`` even relabels its columns across
releases. ``/proc/uptime``, ``/proc/loadavg`` and ``/proc/meminfo`` are
stable kernel interfaces with a documented format. Everything is fetched
in one connection, separated by a marker, so this is one round trip
rather than five.

**Windows** runs PowerShell and asks for JSON, which beats parsing
``systeminfo`` or ``wmic`` text for the same reason. Getting a script
through the SSH -> cmd.exe -> PowerShell chain intact is the hard part:
each layer has its own quoting rules and they disagree about backslashes
and embedded quotes. ``-EncodedCommand`` with base64 UTF-16LE sidesteps
all of it - the script travels as one opaque token no shell tries to
interpret. (This is also why ``SSHClient.run_login_shell`` is not used
against Windows at all: there is no ``/bin/bash`` to wrap with.)
"""

from __future__ import annotations

import base64
import json
from typing import Any

from mcp_server.infra.app_config import HostConfig
from mcp_server.infra.ssh import SSHClient
from mcp_server.resources.host_health.contract import DiskUsage, HostHealth


_MARKER = "===sect==="

_LINUX_SCRIPT = (
    f"cat /proc/uptime; echo '{_MARKER}'; "
    f"cat /proc/loadavg; echo '{_MARKER}'; "
    f"cat /proc/meminfo; echo '{_MARKER}'; "
    f"df -P -k; echo '{_MARKER}'; "
    f"nproc"
)

_WINDOWS_SCRIPT = """
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
[pscustomobject]@{
  uptime_seconds = [int]((Get-Date) - $os.LastBootUpTime).TotalSeconds
  memory_total_kb = [int64]$os.TotalVisibleMemorySize
  memory_available_kb = [int64]$os.FreePhysicalMemory
  cpu_count = [int]$env:NUMBER_OF_PROCESSORS
  cpu_usage_percent = [double]$cpu.Average
  disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    [pscustomobject]@{ mount = $_.DeviceID; total_kb = [int64]($_.Size / 1024); free_kb = [int64]($_.FreeSpace / 1024) }
  })
} | ConvertTo-Json -Compress -Depth 4
""".strip()


def _windows_command() -> str:
    """PowerShell's -EncodedCommand expects base64 of UTF-16LE, which is
    what makes the script immune to re-quoting on the way over."""
    encoded = base64.b64encode(_WINDOWS_SCRIPT.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"


def _parse_meminfo(text: str) -> tuple[int, int]:
    """MemAvailable, not MemFree. MemFree excludes reclaimable page cache,
    so on a healthy machine it looks alarmingly small - MemAvailable is
    the kernel's own estimate of what a new workload could actually get."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return total, available


def _parse_df(text: str) -> list[DiskUsage]:
    """``df -P`` guarantees one line per filesystem (no wrapping) and a
    fixed column order. Only real block devices are kept: tmpfs, overlay
    and friends are kernel bookkeeping, and on a container host they
    otherwise swamp the list.

    Total is taken as used + available, NOT df's own first column. On ext4
    those differ by the ~5% reserved for root: a 479 GB root filesystem
    reports 479 GB total but only 455 GB of used+available. Dividing by
    the raw total gives 49.7% where ``df`` itself says 47%, and a health
    report that disagrees with the command the user would run to check it
    is worse than useless. The reserved blocks aren't space anyone can
    use, so usable space is the honest denominator.
    """
    disks: list[DiskUsage] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6 or not parts[0].startswith("/dev/"):
            continue
        try:
            used, free = int(parts[2]), int(parts[3])
        except ValueError:
            continue
        disks.append(DiskUsage(mount=parts[5], total_kb=used + free, free_kb=free))
    return disks


def _first_float(text: str, default: float = 0.0) -> float:
    parts = text.split()
    try:
        return float(parts[0])
    except (IndexError, ValueError):
        return default


def _gather_linux(config: HostConfig, output: str) -> HostHealth:
    sections = output.split(_MARKER)
    if len(sections) < 5:
        raise RuntimeError(
            f"Unexpected response from {config.name}: got {len(sections)} of 5 sections. "
            f"Output began: {output[:200]!r}"
        )
    uptime, loadavg, meminfo, df_text, nproc = (section.strip() for section in sections[:5])
    total_kb, available_kb = _parse_meminfo(meminfo)

    return HostHealth(
        name=config.name,
        hostname=config.hostname,
        os="linux",
        uptime_seconds=int(_first_float(uptime)),
        cpu_count=int(_first_float(nproc, 1)),
        memory_total_kb=total_kb,
        memory_available_kb=available_kb,
        disks=_parse_df(df_text),
        load_average_1m=_first_float(loadavg),
    )


def _gather_windows(config: HostConfig, output: str) -> HostHealth:
    try:
        # PowerShell may emit a BOM or trailing newline before/after the JSON.
        data: dict[str, Any] = json.loads(output.strip().lstrip("﻿"))
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Could not parse the response from {config.name} as JSON ({error}). "
            f"Output began: {output[:200]!r}"
        ) from error

    raw_disks = data.get("disks") or []
    # ConvertTo-Json collapses a one-element array into a bare object.
    if isinstance(raw_disks, dict):
        raw_disks = [raw_disks]

    return HostHealth(
        name=config.name,
        hostname=config.hostname,
        os="windows",
        uptime_seconds=int(data.get("uptime_seconds", 0)),
        cpu_count=int(data.get("cpu_count", 1)),
        memory_total_kb=int(data.get("memory_total_kb", 0)),
        memory_available_kb=int(data.get("memory_available_kb", 0)),
        disks=[
            DiskUsage(
                mount=str(disk.get("mount", "?")),
                total_kb=int(disk.get("total_kb", 0)),
                free_kb=int(disk.get("free_kb", 0)),
            )
            for disk in raw_disks
        ],
        cpu_usage_percent=float(data.get("cpu_usage_percent") or 0.0),
    )


def collect(config: HostConfig) -> HostHealth:
    """Connect, run the one command for this OS, and parse the result."""
    command = _LINUX_SCRIPT if config.os == "linux" else _windows_command()

    with SSHClient(
        config.hostname,
        config.user,
        key=config.key,
        password=config.password,
    ) as ssh:
        result = ssh.run(command)

    if not result.stdout.strip():
        raise RuntimeError(
            f"No output from {config.name} (exit status {result.exit_status}). "
            f"stderr: {result.stderr.strip()[:200] or '(empty)'}"
        )

    if config.os == "linux":
        return _gather_linux(config, result.stdout)
    return _gather_windows(config, result.stdout)


def _format_duration(seconds: int) -> str:
    days, remainder = divmod(max(seconds, 0), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_report(health: HostHealth) -> str:
    """A compact text report.

    Text rather than raw JSON because this is read by a model that will
    summarize it for a person, and units it can't misread ("14.2 GB free")
    beat a number it has to convert ("14889024" kb). The exact figures are
    still there for anything that needs them.
    """
    lines = [
        f"{health.name} ({health.hostname}, {health.os})",
        f"  Uptime : {_format_duration(health.uptime_seconds)}",
    ]

    if health.load_average_1m is not None:
        saturated = " - above core count" if health.load_average_1m > health.cpu_count else ""
        lines.append(
            f"  CPU    : load average {health.load_average_1m:.2f} "
            f"over {health.cpu_count} cores{saturated}"
        )
    elif health.cpu_usage_percent is not None:
        lines.append(f"  CPU    : {health.cpu_usage_percent:.0f}% across {health.cpu_count} cores")

    lines.append(
        f"  Memory : {health.memory_used_percent}% used "
        f"({health.memory_used_kb / 1048576:.1f} of {health.memory_total_kb / 1048576:.1f} GB)"
    )

    if health.disks:
        lines.append("  Disks  :")
        for disk in health.disks:
            lines.append(
                f"    {disk.mount:<12} {disk.used_percent:>5}% used, "
                f"{disk.free_kb / 1048576:.1f} GB free of {disk.total_kb / 1048576:.1f} GB"
            )
    else:
        lines.append("  Disks  : none reported")

    return "\n".join(lines)

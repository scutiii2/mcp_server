"""Tests for the host-health domain logic.

Parsing is tested against real command output pasted verbatim, because
the entire risk in this module is that a format differs from what was
assumed. A test built from output this code already knows how to parse
proves nothing.

No SSH: collect() is exercised with a fake client, and the parsers
directly.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from src.infra.app_config import HostConfig
from src.resources.host_health import domain
from src.resources.host_health.contract import DiskUsage, HostHealth


LINUX_HOST = HostConfig(name="zima", hostname="192.168.1.10", user="root", os="linux", key="/k")
WINDOWS_HOST = HostConfig(name="desktop", hostname="192.168.1.20", user="User", os="windows", password="pw")

# Real output from a Debian box.
MEMINFO = """MemTotal:       16316820 kB
MemFree:          521484 kB
MemAvailable:   13204592 kB
Buffers:          210044 kB
Cached:         12180960 kB
SwapCached:            0 kB
"""

DF = """Filesystem     1024-blocks      Used Available Capacity Mounted on
udev               8123456         0   8123456       0% /dev
tmpfs              1631684      2108   1629576       1% /run
/dev/nvme0n1p2   479634816 213847292 241371136      47% /
/dev/nvme0n1p1      523248      6132    517116       2% /boot/efi
overlay          479634816 213847292 241371136      47% /var/lib/docker/overlay2/abc/merged
"""


def _linux_output(uptime="184523.44 1470291.12", loadavg="0.52 0.61 0.58 2/1284 30411",
                  meminfo=MEMINFO, df=DF, nproc="8") -> str:
    return f"\n{domain._MARKER}\n".join([uptime, loadavg, meminfo, df, nproc])


# --- Linux parsing -----------------------------------------------------


def test_linux_health_is_parsed_from_proc():
    health = domain._gather_linux(LINUX_HOST, _linux_output())

    assert health.os == "linux"
    assert health.uptime_seconds == 184523
    assert health.cpu_count == 8
    assert health.load_average_1m == 0.52
    assert health.memory_total_kb == 16316820


def test_memavailable_is_preferred_over_memfree():
    """MemFree excludes reclaimable page cache, so on any healthy machine
    it looks alarmingly small - here it would report 97% memory used
    instead of 19%."""
    health = domain._gather_linux(LINUX_HOST, _linux_output())

    assert health.memory_available_kb == 13204592  # MemAvailable, not MemFree's 521484
    assert health.memory_used_percent == pytest.approx(19.1, abs=0.1)


def test_memfree_is_used_when_memavailable_is_absent():
    """MemAvailable only exists on kernels 3.14+; falling back beats
    reporting zero."""
    without = MEMINFO.replace("MemAvailable:   13204592 kB\n", "")

    health = domain._gather_linux(LINUX_HOST, _linux_output(meminfo=without))

    assert health.memory_available_kb == 521484


def test_only_real_block_devices_are_reported():
    """tmpfs/udev/overlay are kernel bookkeeping - on a container host
    they'd swamp the list, and 'udev is 0% full' is not disk health."""
    health = domain._gather_linux(LINUX_HOST, _linux_output())

    assert [disk.mount for disk in health.disks] == ["/", "/boot/efi"]


def test_disk_percentages_match_what_df_itself_reports():
    """Regression: dividing by df's raw total column gave 49.7% where df
    says 47%, because ext4 reserves ~5% for root and df excludes it. A
    report that disagrees with the command someone would run to check it
    is worse than no report."""
    health = domain._gather_linux(LINUX_HOST, _linux_output())
    root = health.disks[0]

    assert root.used_percent == pytest.approx(47.0, abs=0.5)


def test_reserved_blocks_are_excluded_from_the_total():
    health = domain._gather_linux(LINUX_HOST, _linux_output())
    root = health.disks[0]

    # used + available, not df's 479634816 raw total.
    assert root.total_kb == 213847292 + 241371136


def test_truncated_output_fails_loudly():
    """A half-delivered response should not silently become a host that
    reports 0 bytes of memory and looks broken."""
    with pytest.raises(RuntimeError, match="of 5 sections"):
        domain._gather_linux(LINUX_HOST, "184523.44 1470291.12")


def test_unparseable_numbers_do_not_crash():
    """Better a zero with the rest of the report intact than an exception
    that loses the disk and memory figures too."""
    health = domain._gather_linux(LINUX_HOST, _linux_output(uptime="not-a-number", nproc=""))

    assert health.uptime_seconds == 0
    assert health.cpu_count == 1


# --- Windows parsing ---------------------------------------------------


WINDOWS_JSON = json.dumps(
    {
        "uptime_seconds": 93784,
        "memory_total_kb": 33401234,
        "memory_available_kb": 18220100,
        "cpu_count": 16,
        "cpu_usage_percent": 12.0,
        "disks": [
            {"mount": "C:", "total_kb": 998765432, "free_kb": 214365432},
            {"mount": "D:", "total_kb": 1953514584, "free_kb": 1204365432},
        ],
    }
)


def test_windows_health_is_parsed_from_json():
    health = domain._gather_windows(WINDOWS_HOST, WINDOWS_JSON)

    assert health.os == "windows"
    assert health.uptime_seconds == 93784
    assert health.cpu_count == 16
    assert health.cpu_usage_percent == 12.0
    assert [disk.mount for disk in health.disks] == ["C:", "D:"]


def test_single_disk_object_is_accepted_as_a_list():
    """ConvertTo-Json collapses a one-element array into a bare object, so
    a machine with only C: returns a different shape than one with two
    drives."""
    single = json.loads(WINDOWS_JSON)
    single["disks"] = {"mount": "C:", "total_kb": 100, "free_kb": 40}

    health = domain._gather_windows(WINDOWS_HOST, json.dumps(single))

    assert [disk.mount for disk in health.disks] == ["C:"]


def test_leading_bom_is_tolerated():
    """PowerShell writes a BOM in some console encodings, which json
    refuses."""
    health = domain._gather_windows(WINDOWS_HOST, "﻿" + WINDOWS_JSON)

    assert health.uptime_seconds == 93784


def test_non_json_response_fails_with_the_output_quoted():
    """The usual cause is a PowerShell error printed before the JSON, and
    seeing that text is the whole diagnosis."""
    with pytest.raises(RuntimeError, match="Could not parse"):
        domain._gather_windows(WINDOWS_HOST, "Get-CimInstance : Access denied")


def test_windows_never_reports_a_load_average():
    """Load average and CPU percentage are different measurements; the one
    Windows can't answer stays None rather than being faked."""
    health = domain._gather_windows(WINDOWS_HOST, WINDOWS_JSON)

    assert health.load_average_1m is None


def test_linux_never_reports_a_cpu_percentage():
    health = domain._gather_linux(LINUX_HOST, _linux_output())

    assert health.cpu_usage_percent is None


# --- command construction ----------------------------------------------


def test_windows_command_is_base64_utf16le():
    """-EncodedCommand is what keeps the script intact through
    SSH -> cmd.exe -> PowerShell, each of which would otherwise re-quote
    it."""
    command = domain._windows_command()
    encoded = command.rsplit(" ", 1)[1]

    decoded = base64.b64decode(encoded).decode("utf-16-le")

    assert command.startswith("powershell -NoProfile -NonInteractive -EncodedCommand ")
    assert "ConvertTo-Json" in decoded
    assert "Win32_LogicalDisk" in decoded


def test_windows_command_contains_no_quotes_to_be_mangled():
    """The point of encoding: nothing downstream sees a quote at all."""
    command = domain._windows_command()

    assert '"' not in command
    assert "'" not in command


# --- collect() dispatch ------------------------------------------------


def _fake_ssh(stdout: str):
    client = MagicMock()
    client.__enter__.return_value.run.return_value = MagicMock(
        stdout=stdout, stderr="", exit_status=0
    )
    return client


def test_collect_uses_proc_for_linux_hosts():
    fake = _fake_ssh(_linux_output())
    with patch("src.resources.host_health.domain.SSHClient", return_value=fake):
        health = domain.collect(LINUX_HOST)

    ran = fake.__enter__.return_value.run.call_args.args[0]
    assert "/proc/meminfo" in ran
    assert health.os == "linux"


def test_collect_uses_powershell_for_windows_hosts():
    fake = _fake_ssh(WINDOWS_JSON)
    with patch("src.resources.host_health.domain.SSHClient", return_value=fake):
        health = domain.collect(WINDOWS_HOST)

    ran = fake.__enter__.return_value.run.call_args.args[0]
    assert ran.startswith("powershell ")
    assert health.os == "windows"


def test_collect_is_one_round_trip():
    """Five separate commands would be five SSH round trips; the marker
    exists so it's one."""
    fake = _fake_ssh(_linux_output())
    with patch("src.resources.host_health.domain.SSHClient", return_value=fake):
        domain.collect(LINUX_HOST)

    assert fake.__enter__.return_value.run.call_count == 1


def test_empty_output_reports_the_exit_status_and_stderr():
    client = MagicMock()
    client.__enter__.return_value.run.return_value = MagicMock(
        stdout="", stderr="Permission denied", exit_status=1
    )
    with patch("src.resources.host_health.domain.SSHClient", return_value=client):
        with pytest.raises(RuntimeError, match="Permission denied"):
            domain.collect(LINUX_HOST)


# --- report formatting -------------------------------------------------


def test_report_shows_gigabytes_not_kibibytes():
    """A model summarizing this for a person shouldn't have to do unit
    conversion it can get wrong."""
    report = domain.format_report(domain._gather_linux(LINUX_HOST, _linux_output()))

    assert "GB" in report
    assert "16316820" not in report


def test_report_flags_load_above_core_count():
    health = domain._gather_linux(LINUX_HOST, _linux_output(loadavg="14.30 9.10 6.02 2/1284 30411"))

    assert "above core count" in domain.format_report(health)


def test_report_omits_the_metric_the_os_cannot_provide():
    linux_report = domain.format_report(domain._gather_linux(LINUX_HOST, _linux_output()))
    windows_report = domain.format_report(domain._gather_windows(WINDOWS_HOST, WINDOWS_JSON))

    assert "load average" in linux_report
    assert "load average" not in windows_report
    assert "% across" in windows_report


def test_report_handles_a_host_with_no_disks():
    health = HostHealth(
        name="x", hostname="h", os="linux", uptime_seconds=60, cpu_count=1,
        memory_total_kb=100, memory_available_kb=50, disks=[],
    )

    assert "none reported" in domain.format_report(health)


def test_zero_sized_disk_does_not_divide_by_zero():
    disk = DiskUsage(mount="/empty", total_kb=0, free_kb=0)

    assert disk.used_percent == 0.0

"""Shapes for the host-health resource.

Fields that only one operating system can answer are ``None`` on the
other, rather than being coerced into a shared number. Linux load average
and Windows CPU-load percentage are genuinely different measurements -
load average counts runnable processes and can exceed the core count,
while the percentage is bounded at 100 - so presenting either as the
other would be inventing data. A model reading this can say "not
available on Windows"; it cannot un-mislead itself about a fabricated
figure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiskUsage(BaseModel):
    mount: str = Field(description="Mount point (Linux) or drive letter (Windows).")
    total_kb: int = Field(description="Total size in kibibytes.")
    free_kb: int = Field(description="Free space in kibibytes.")

    @property
    def used_kb(self) -> int:
        return max(self.total_kb - self.free_kb, 0)

    @property
    def used_percent(self) -> float:
        if self.total_kb <= 0:
            return 0.0
        return round(self.used_kb / self.total_kb * 100, 1)


class HostHealth(BaseModel):
    name: str = Field(description="The configured name of the host.")
    hostname: str = Field(description="Address actually connected to.")
    os: str = Field(description="'linux' or 'windows'.")
    uptime_seconds: int = Field(description="Seconds since last boot.")
    cpu_count: int = Field(description="Logical processors.")
    memory_total_kb: int
    memory_available_kb: int
    disks: list[DiskUsage] = Field(default_factory=list)
    load_average_1m: float | None = Field(
        default=None,
        description="Linux only: runnable processes averaged over 1 minute. None on Windows.",
    )
    cpu_usage_percent: float | None = Field(
        default=None,
        description="Windows only: instantaneous CPU load percentage. None on Linux.",
    )

    @property
    def memory_used_kb(self) -> int:
        return max(self.memory_total_kb - self.memory_available_kb, 0)

    @property
    def memory_used_percent(self) -> float:
        if self.memory_total_kb <= 0:
            return 0.0
        return round(self.memory_used_kb / self.memory_total_kb * 100, 1)

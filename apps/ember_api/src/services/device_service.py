"""Device fingerprinting (port of chat_app's services/security/fingerprint.py).

A device is a hash of what the browser tells every request - its
User-Agent, Accept-Language and the /24 (IPv4) or /64 (IPv6) network it
comes from - so it needs no script or cookie in the browser. It is a
signal, not proof: the same browser on a new network counts as a new
device, and two identical browsers on one network look the same.

Like chat_app's "log_only" behavior, a login from a new device is allowed
and written to the activity log; the account's own devices are listed on
the Account page, where one can be forgotten.
"""

from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models.known_device import KnownDevice

SIGNALS = ("user_agent", "accept_language", "ip_subnet")
USER_AGENT_MAX = 300


def ip_subnet(ip_address: str) -> str:
    """The network an address belongs to: /24 for IPv4, /64 for IPv6, so a
    new address from the same provider pool isn't a new device."""
    try:
        address = ipaddress.ip_address(ip_address)
    except ValueError:
        return ip_address
    prefix = 24 if address.version == 4 else 64
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


@dataclass(frozen=True)
class DeviceSignals:
    user_agent: str
    accept_language: str
    ip_address: str

    @property
    def subnet(self) -> str:
        return ip_subnet(self.ip_address)

    def fingerprint(self, signals: tuple[str, ...] = SIGNALS) -> str:
        values = {"user_agent": self.user_agent, "accept_language": self.accept_language, "ip_subnet": self.subnet}
        raw = "|".join(values.get(signal, "") for signal in signals)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeviceService:
    def __init__(self, session: AsyncSession, signals: tuple[str, ...] = SIGNALS) -> None:
        self._session = session
        self._signals = signals

    def fingerprint(self, device: DeviceSignals) -> str:
        return device.fingerprint(self._signals)

    async def record(self, account_id: int, device: DeviceSignals) -> bool:
        """Notes a login from `device`; True when the account never logged in
        from it before."""
        fingerprint = self.fingerprint(device)
        known = await self._session.scalar(
            select(KnownDevice).where(KnownDevice.account_id == account_id, KnownDevice.fingerprint_hash == fingerprint)
        )
        now = utcnow()
        if known is not None:
            known.last_seen_at = now
            await self._session.commit()
            return False
        self._session.add(
            KnownDevice(
                account_id=account_id,
                fingerprint_hash=fingerprint,
                user_agent=device.user_agent[:USER_AGENT_MAX],
                ip_subnet=device.subnet,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        await self._session.commit()
        return True

    async def list(self, account_id: int) -> list[KnownDevice]:
        """Most recently used first."""
        rows = await self._session.scalars(
            select(KnownDevice).where(KnownDevice.account_id == account_id).order_by(KnownDevice.last_seen_at.desc())
        )
        return list(rows)

    async def forget(self, account_id: int, device_id: int) -> bool:
        """The next login from it counts as a new device again."""
        result = await self._session.execute(
            delete(KnownDevice).where(KnownDevice.account_id == account_id, KnownDevice.id == device_id)
        )
        await self._session.commit()
        return result.rowcount > 0


def describe(user_agent: str) -> str:
    """"Firefox on Windows"-style label for the activity log and the
    Account page; the raw User-Agent is shown next to it."""
    ua = user_agent.lower()
    browser = next(
        (name for key, name in (("edg/", "Edge"), ("opr/", "Opera"), ("firefox/", "Firefox"), ("chrome/", "Chrome"),
                                ("safari/", "Safari")) if key in ua),
        "Unknown browser",
    )
    system = next(
        (name for key, name in (("windows", "Windows"), ("android", "Android"), ("iphone", "iOS"), ("ipad", "iOS"),
                                ("mac os", "macOS"), ("linux", "Linux")) if key in ua),
        "unknown system",
    )
    return f"{browser} on {system}"

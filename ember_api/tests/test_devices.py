"""Device fingerprinting: a login from a new device is logged, and the
account lists (and forgets) its devices."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.config import SecuritySettings
from src.services.device_service import DeviceSignals, describe, ip_subnet
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_logs import messages, my_id

FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"


def login_with(client: TestClient, user_agent: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        headers={"User-Agent": user_agent, "Accept-Language": "en-US"},
    )
    assert response.status_code == 200, response.text


def new_device_lines(client: TestClient) -> list[str]:
    return [m for m in messages(client, "action", my_id(client)) if m.startswith("First login from this device")]


def test_new_devices_are_logged_once(client_factory) -> None:
    client = client_factory(address="198.51.100.20")
    login_with(client, FIREFOX)
    login_with(client, FIREFOX)
    assert new_device_lines(client) == ["First login from this device: Firefox on Windows, 198.51.100.0/24"]

    login_with(client, PHONE)
    assert len(new_device_lines(client)) == 2


def test_devices_are_listed_and_forgotten(client_factory) -> None:
    client = client_factory(address="198.51.100.20")
    login_with(client, PHONE)
    login_with(client, FIREFOX)

    devices = client.get("/api/account/devices", headers={"User-Agent": FIREFOX, "Accept-Language": "en-US"}).json()
    assert [(d["label"], d["current"]) for d in devices] == [("Firefox on Windows", True), ("Safari on iOS", False)]
    assert devices[0]["ip_subnet"] == "198.51.100.0/24"

    phone = devices[1]["id"]
    assert client.delete(f"/api/account/devices/{phone}").status_code == 204
    assert client.delete(f"/api/account/devices/{phone}").status_code == 404
    assert len(client.get("/api/account/devices").json()) == 1

    login_with(client, PHONE)
    assert len(new_device_lines(client)) == 3  # new again once forgotten


def test_devices_are_private_and_need_login(client_factory, email: FakeEmailSender) -> None:
    client = client_factory()
    assert client.get("/api/account/devices").status_code == 401
    make_member(client, email)
    login_with(client, FIREFOX)
    root_device = client.get("/api/account/devices").json()[0]["id"]
    client.post("/api/auth/logout", json={})
    login(client, "alice")
    assert client.delete(f"/api/account/devices/{root_device}").status_code == 404


def test_fingerprinting_can_be_switched_off(client_factory) -> None:
    client = client_factory(security=SecuritySettings(fingerprint_enabled=False))
    login_with(client, FIREFOX)
    assert new_device_lines(client) == []
    assert client.get("/api/account/devices").json() == []


def test_fingerprint_signals() -> None:
    a = DeviceSignals(FIREFOX, "en-US", "203.0.113.5")
    moved = DeviceSignals(FIREFOX, "en-US", "203.0.113.200")
    other_net = DeviceSignals(FIREFOX, "en-US", "192.0.2.5")
    assert a.fingerprint() == moved.fingerprint()
    assert a.fingerprint() != other_net.fingerprint()
    assert a.fingerprint(("user_agent",)) == other_net.fingerprint(("user_agent",))
    assert ip_subnet("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::/64"
    assert ip_subnet("testclient") == "testclient"
    assert describe("curl/8.0") == "Unknown browser on unknown system"


def test_bad_fingerprint_config_is_refused() -> None:
    with pytest.raises(ValueError):
        SecuritySettings.from_config({"fingerprint": {"signals": ["cookies"]}})
    assert SecuritySettings.from_config({"fingerprint": {"enabled": False}}).fingerprint_enabled is False

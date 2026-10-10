"""is_exposed_without_token(): a server beyond loopback with no internal token."""

import pytest

from src.services.internal_token import is_exposed_without_token


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_are_not_exposed(host):
    assert not is_exposed_without_token(host, "")


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "127.0.0.2", "ember.internal", ""])
def test_any_other_host_is_exposed_without_a_token(host):
    assert is_exposed_without_token(host, "")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "127.0.0.1"])
def test_a_token_closes_the_exposure(host):
    assert not is_exposed_without_token(host, "secret")

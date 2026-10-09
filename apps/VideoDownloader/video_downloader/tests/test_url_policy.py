from __future__ import annotations

import socket

import pytest

from src.errors import DownloaderError, ErrorCode
from src.policy.url_policy import UrlPolicy, is_public_ip


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111", "64:ff9b::808:808"])
def test_public_addresses(ip):
    assert is_public_ip(ip)


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
     "224.0.0.1", "::1", "::", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
     "64:ff9b::7f00:1", "64:ff9b::a00:1", "::127.0.0.1", "::10.0.0.1"],
)
def test_non_public_addresses(ip):
    assert not is_public_ip(ip)


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise socket.gaierror("not found")
        return mapping[host]

    return resolve


@pytest.fixture
def policy():
    return UrlPolicy(resolver_for({
        "example.com": ["93.184.216.34"],
        "evil.example": ["10.0.0.5"],
        "mixed.example": ["93.184.216.34", "127.0.0.1"],
    }))


async def test_accepts_public_https_and_trims(policy):
    assert await policy.check("  https://example.com/watch?v=1  ") == "https://example.com/watch?v=1"


@pytest.mark.parametrize("url", ["", "not a url", "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)",
                                 "https://", "https://user:pw@example.com/", "https://" + "a" * 3000 + ".com"])
async def test_rejects_bad_shapes(policy, url):
    with pytest.raises(DownloaderError) as error:
        await policy.check(url)
    assert error.value.code == ErrorCode.INVALID_URL


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.10/x", "http://evil.example/x",
    "http://mixed.example/x", "https://example.com:8080/x", "http://169.254.169.254/latest/meta-data",
])
async def test_blocks_private_hosts_and_odd_ports(policy, url):
    with pytest.raises(DownloaderError) as error:
        await policy.check(url)
    assert error.value.code == ErrorCode.BLOCKED_HOST


async def test_unknown_host_is_invalid_url(policy):
    with pytest.raises(DownloaderError) as error:
        await policy.check("https://nope.example/x")
    assert error.value.code == ErrorCode.INVALID_URL


async def test_allows_port_443_and_80(policy):
    assert await policy.check("https://example.com:443/x")
    assert await policy.check("http://example.com:80/x")

"""Unit tests for is_loopback_host.

Covers:
    - loopback classification: IP literals, hostnames, bracketed/mapped IPv6
    - non-loopback classification: LAN IPs, hostnames, bind-all address
    - no DNS resolution is performed
"""

from unittest.mock import patch

import pytest

from hassette.utils.net_utils import is_loopback_host

LOOPBACK_HOSTS = [
    "localhost",
    "LOCALHOST",
    "127.0.0.1",
    "127.0.0.53",
    "::1",
    "[::1]",
    "::ffff:127.0.0.1",
]

NON_LOOPBACK_HOSTS = [
    "192.168.1.5",
    "example.com",
    "0.0.0.0",
]


@pytest.mark.parametrize("host", LOOPBACK_HOSTS)
def test_classifies_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host) is True


@pytest.mark.parametrize("host", NON_LOOPBACK_HOSTS)
def test_classifies_non_loopback_hosts(host: str) -> None:
    assert is_loopback_host(host) is False


def test_performs_no_dns_resolution() -> None:
    """A hostname that isn't in the fixed set never triggers a DNS lookup."""
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        assert is_loopback_host("example.com") is False
        assert is_loopback_host("localhost") is True
    mock_getaddrinfo.assert_not_called()

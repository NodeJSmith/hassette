"""Unit tests for ``trusted_proxies`` peer matching: IP/CIDR/hostname parsing, DNS resolution,
periodic refresh, and the peer-match function's header-free signature.
"""

import asyncio
import re
import socket
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from hassette.exceptions import TrustedProxyConfigError
from hassette.test_utils import make_addrinfo, patch_loop_getaddrinfo
from hassette.web.auth.trusted_proxies import is_trusted_peer, refresh_trusted_proxies, resolve_trusted_proxies


class TestResolveTrustedProxiesLiteral:
    async def test_ip_entry_matches_only_that_ip(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert is_trusted_peer("192.168.1.10", trusted) is True
        assert is_trusted_peer("192.168.1.11", trusted) is False

    async def test_cidr_entry_matches_any_address_in_range(self) -> None:
        trusted = await resolve_trusted_proxies(("10.0.0.0/24",))

        assert is_trusted_peer("10.0.0.1", trusted) is True
        assert is_trusted_peer("10.0.0.254", trusted) is True
        assert is_trusted_peer("10.0.1.1", trusted) is False

    async def test_malformed_entry_raises_at_parse_time(self) -> None:
        # Not a valid IP/CIDR literal, and DNS resolution also fails for it — this is the
        # "neither a literal nor a resolvable hostname" case that must fail loudly rather
        # than silently skip the bad entry.
        with (
            patch_loop_getaddrinfo(side_effect=socket.gaierror("not found")),
            pytest.raises(TrustedProxyConfigError, match="not-a-valid-entry"),
        ):
            await resolve_trusted_proxies(("not-a-valid-entry!!!",))

    async def test_non_matching_address_not_trusted_with_no_header_input(self) -> None:
        """The match function only ever sees an address string — there is no headers
        parameter through which a spoofed value could influence the result.
        """
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert is_trusted_peer("203.0.113.4", trusted) is False


class TestResolveTrustedProxiesRejectsEntireAddressSpace:
    async def test_rejects_ipv4_entire_address_space(self) -> None:
        with pytest.raises(TrustedProxyConfigError, match=re.escape("0.0.0.0/0")):
            await resolve_trusted_proxies(("0.0.0.0/0",))

    async def test_rejects_ipv6_entire_address_space(self) -> None:
        with pytest.raises(TrustedProxyConfigError, match=re.escape("::/0")):
            await resolve_trusted_proxies(("::/0",))

    async def test_narrow_cidr_is_not_rejected(self) -> None:
        """A /8 is a legitimate operator choice, not a broad-CIDR heuristic violation."""
        trusted = await resolve_trusted_proxies(("10.0.0.0/8",))

        assert is_trusted_peer("10.255.255.255", trusted) is True


class TestResolveTrustedProxiesHostname:
    async def test_hostname_entry_resolves_and_matches_resolved_ip(self) -> None:
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            trusted = await resolve_trusted_proxies(("proxy.internal",))

        assert is_trusted_peer("172.30.32.2", trusted) is True
        assert is_trusted_peer("172.30.32.3", trusted) is False

    async def test_hostname_resolution_failure_raises_at_parse_time(self) -> None:
        with (
            patch_loop_getaddrinfo(side_effect=socket.gaierror("no such host")),
            pytest.raises(TrustedProxyConfigError, match=re.escape("proxy.internal")),
        ):
            await resolve_trusted_proxies(("proxy.internal",))

    async def test_resolution_exceeding_timeout_raises_trusted_proxy_config_error(self) -> None:
        """A resolver that never returns must not hang ``_resolve_hostname`` forever -- the
        call is bounded by ``_DNS_RESOLVE_TIMEOUT_SECONDS`` and a timeout surfaces as the same
        ``TrustedProxyConfigError`` any other resolution failure raises, not an unhandled
        ``TimeoutError``.
        """

        async def hang(*_args: object, **_kwargs: object) -> list[tuple[Any, ...]]:
            await asyncio.sleep(10)
            return [make_addrinfo("172.30.32.2")]

        with (
            patch("hassette.web.auth.trusted_proxies._DNS_RESOLVE_TIMEOUT_SECONDS", 0.01),
            patch("asyncio.BaseEventLoop.getaddrinfo", new_callable=AsyncMock, side_effect=hang),
            pytest.raises(TrustedProxyConfigError, match=re.escape("proxy.internal")),
        ):
            await resolve_trusted_proxies(("proxy.internal",))


class TestRefreshTrustedProxies:
    async def test_changed_dns_response_updates_trusted_set(self) -> None:
        """Simulated periodic-refresh tick: two successive resolver results, second call's IP
        becomes trusted, first call's IP is no longer trusted.
        """
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            trusted = await resolve_trusted_proxies(("proxy.internal",))
        assert is_trusted_peer("172.30.32.2", trusted) is True

        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.9")]):
            refreshed = await refresh_trusted_proxies(trusted)

        assert is_trusted_peer("172.30.32.9", refreshed) is True
        assert is_trusted_peer("172.30.32.2", refreshed) is False

    async def test_transient_refresh_failure_keeps_last_known_good_address(self) -> None:
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            trusted = await resolve_trusted_proxies(("proxy.internal",))

        with patch_loop_getaddrinfo(side_effect=socket.gaierror("temporary failure")):
            refreshed = await refresh_trusted_proxies(trusted)

        # The stale-but-last-known-good address is still trusted — a flaky DNS blip must not
        # lock out the proxy.
        assert is_trusted_peer("172.30.32.2", refreshed) is True

    async def test_refresh_does_not_affect_literal_entries(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        refreshed = await refresh_trusted_proxies(trusted)

        assert refreshed.literal_networks == trusted.literal_networks
        assert is_trusted_peer("192.168.1.10", refreshed) is True

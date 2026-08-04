"""Unit tests for web API auth token resolution: explicit config, existing token file,
freshly generated token, corrupt-file recovery, and distinct per-branch logging.

Also covers ``trusted_proxies`` peer matching: IP/CIDR/hostname parsing, DNS resolution,
periodic refresh, and the peer-match function's header-free signature.
"""

import logging
import re
import socket
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError, TrustedProxyConfigError
from hassette.web.auth import (
    TOKEN_FILENAME,
    is_trusted_peer,
    refresh_trusted_proxies,
    resolve_auth_token,
    resolve_trusted_proxies,
)


def _make_config(**overrides: Any) -> WebApiConfig:
    return WebApiConfig.model_validate(overrides)


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left ``propagate`` set to False (e.g. via
    ``enable_basic_logging()``); caplog relies on propagation to the root logger. Same
    workaround as ``tests/unit/test_autodetect_apps.py``.
    """
    logging.getLogger("hassette").propagate = True


class TestResolveAuthTokenExplicitConfig:
    def test_uses_configured_token_without_touching_disk(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _make_config(auth_token=SecretStr("configured-token-value"))

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        assert token == "configured-token-value"
        assert not (tmp_path / TOKEN_FILENAME).exists()

        messages = [r.message for r in caplog.records]
        assert any("configured" in m.lower() for m in messages), messages


class TestResolveAuthTokenExistingFile:
    def test_loads_existing_token_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("existing-token-value\n", encoding="utf-8")
        config = _make_config()

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        assert token == "existing-token-value"

        messages = [r.message for r in caplog.records]
        assert any("existing" in m.lower() and str(token_path) in m for m in messages), messages


class TestResolveAuthTokenGenerated:
    def test_generates_persists_and_logs_url(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        config = _make_config(host="127.0.0.1", port=8126)

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        token_path = tmp_path / TOKEN_FILENAME
        assert token_path.exists()
        assert token_path.read_text(encoding="utf-8") == token
        assert len(token) > 32  # secrets.token_urlsafe(32) produces a 43-char string

        mode = stat.S_IMODE(token_path.stat().st_mode)
        assert mode == 0o600, f"expected mode 0600, got {oct(mode)}"

        messages = [r.message for r in caplog.records]
        generated_messages = [m for m in messages if "generated" in m.lower()]
        assert generated_messages, messages
        assert any("http://127.0.0.1:8126" in m for m in generated_messages), generated_messages

    def test_no_leftover_temp_file(self, tmp_path: Path) -> None:
        config = _make_config()
        resolve_auth_token(config, tmp_path)

        remaining = {p.name for p in tmp_path.iterdir()}
        assert remaining == {TOKEN_FILENAME}, remaining

    def test_write_failure_raises_named_exception(self, tmp_path: Path) -> None:
        config = _make_config()

        with (
            patch("hassette.web.auth.os.open", side_effect=OSError("disk full")),
            pytest.raises(AuthTokenWriteError) as exc_info,
        ):
            resolve_auth_token(config, tmp_path)

        err = exc_info.value
        assert err.path == tmp_path / TOKEN_FILENAME
        assert isinstance(err.original_error, OSError)
        assert str(tmp_path / TOKEN_FILENAME) in str(err)
        assert "disk full" in str(err)

        # No token file should have been left behind by the failed write.
        assert not (tmp_path / TOKEN_FILENAME).exists()


class TestResolveAuthTokenCorruptFile:
    def test_empty_file_falls_back_to_generation(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("", encoding="utf-8")
        config = _make_config()

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        assert token  # a fresh token was generated
        assert token_path.read_text(encoding="utf-8") == token

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log line for the corrupt/empty token file"
        assert any(str(token_path) in r.message for r in error_records), [r.message for r in error_records]

        # Resolution still succeeds and reaches the "generated" branch, not a crash.
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("generated" in r.message.lower() for r in info_records), [r.message for r in info_records]

    def test_undecodable_content_falls_back_to_generation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_bytes(b"\xff\xfe\x00garbage-not-utf8")
        config = _make_config()

        with caplog.at_level("ERROR", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        assert token
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log line for undecodable token file content"

    def test_corrupt_file_does_not_raise(self, tmp_path: Path) -> None:
        """Resolution succeeds (returns) rather than propagating an exception."""
        token_path = tmp_path / TOKEN_FILENAME
        token_path.write_text("", encoding="utf-8")
        config = _make_config()

        token = resolve_auth_token(config, tmp_path)

        assert isinstance(token, str)
        assert token


class TestResolveAuthTokenDistinctLogMessages:
    def test_all_three_branches_produce_distinct_messages(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Each resolution branch logs a distinct, identifiable INFO message."""
        messages: list[str] = []

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            resolve_auth_token(_make_config(auth_token=SecretStr("explicit-value")), tmp_path / "a")
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        existing_dir = tmp_path / "b"
        existing_dir.mkdir()
        (existing_dir / TOKEN_FILENAME).write_text("pre-existing-value", encoding="utf-8")
        with caplog.at_level("INFO", logger="hassette.web.auth"):
            resolve_auth_token(_make_config(), existing_dir)
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            resolve_auth_token(_make_config(), tmp_path / "c")
        messages.append(next(r.message for r in caplog.records if r.levelno == logging.INFO))
        caplog.clear()

        assert len(set(messages)) == 3, f"expected 3 distinct messages, got: {messages}"


def _addrinfo(ip: str) -> tuple[Any, ...]:
    """Build one ``socket.getaddrinfo``-shaped result tuple for ``ip``."""
    if ":" in ip:
        return (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))


class TestResolveTrustedProxiesLiteral:
    def test_ip_entry_matches_only_that_ip(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert is_trusted_peer("192.168.1.10", trusted) is True
        assert is_trusted_peer("192.168.1.11", trusted) is False

    def test_cidr_entry_matches_any_address_in_range(self) -> None:
        trusted = resolve_trusted_proxies(("10.0.0.0/24",))

        assert is_trusted_peer("10.0.0.1", trusted) is True
        assert is_trusted_peer("10.0.0.254", trusted) is True
        assert is_trusted_peer("10.0.1.1", trusted) is False

    def test_malformed_entry_raises_at_parse_time(self) -> None:
        # Not a valid IP/CIDR literal, and DNS resolution also fails for it — this is the
        # "neither a literal nor a resolvable hostname" case that must fail loudly rather
        # than silently skip the bad entry.
        with (
            patch("hassette.web.auth.socket.getaddrinfo", side_effect=socket.gaierror("not found")),
            pytest.raises(TrustedProxyConfigError, match="not-a-valid-entry"),
        ):
            resolve_trusted_proxies(("not-a-valid-entry!!!",))

    def test_non_matching_address_not_trusted_with_no_header_input(self) -> None:
        """The match function only ever sees an address string — there is no headers
        parameter through which a spoofed value could influence the result.
        """
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert is_trusted_peer("203.0.113.4", trusted) is False


class TestResolveTrustedProxiesRejectsEntireAddressSpace:
    def test_rejects_ipv4_entire_address_space(self) -> None:
        with pytest.raises(TrustedProxyConfigError, match=re.escape("0.0.0.0/0")):
            resolve_trusted_proxies(("0.0.0.0/0",))

    def test_rejects_ipv6_entire_address_space(self) -> None:
        with pytest.raises(TrustedProxyConfigError, match=re.escape("::/0")):
            resolve_trusted_proxies(("::/0",))

    def test_narrow_cidr_is_not_rejected(self) -> None:
        """A /8 is a legitimate operator choice, not a broad-CIDR heuristic violation."""
        trusted = resolve_trusted_proxies(("10.0.0.0/8",))

        assert is_trusted_peer("10.255.255.255", trusted) is True


class TestResolveTrustedProxiesHostname:
    def test_hostname_entry_resolves_and_matches_resolved_ip(self) -> None:
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[_addrinfo("172.30.32.2")]):
            trusted = resolve_trusted_proxies(("proxy.internal",))

        assert is_trusted_peer("172.30.32.2", trusted) is True
        assert is_trusted_peer("172.30.32.3", trusted) is False

    def test_hostname_resolution_failure_raises_at_parse_time(self) -> None:
        with (
            patch("hassette.web.auth.socket.getaddrinfo", side_effect=socket.gaierror("no such host")),
            pytest.raises(TrustedProxyConfigError, match=re.escape("proxy.internal")),
        ):
            resolve_trusted_proxies(("proxy.internal",))


class TestRefreshTrustedProxies:
    def test_changed_dns_response_updates_trusted_set(self) -> None:
        """Simulated periodic-refresh tick: two successive ``socket.getaddrinfo`` results,
        second call's IP becomes trusted, first call's IP is no longer trusted.
        """
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[_addrinfo("172.30.32.2")]):
            trusted = resolve_trusted_proxies(("proxy.internal",))
        assert is_trusted_peer("172.30.32.2", trusted) is True

        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[_addrinfo("172.30.32.9")]):
            refreshed = refresh_trusted_proxies(trusted)

        assert is_trusted_peer("172.30.32.9", refreshed) is True
        assert is_trusted_peer("172.30.32.2", refreshed) is False

    def test_transient_refresh_failure_keeps_last_known_good_address(self) -> None:
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[_addrinfo("172.30.32.2")]):
            trusted = resolve_trusted_proxies(("proxy.internal",))

        with patch("hassette.web.auth.socket.getaddrinfo", side_effect=socket.gaierror("temporary failure")):
            refreshed = refresh_trusted_proxies(trusted)

        # The stale-but-last-known-good address is still trusted — a flaky DNS blip must not
        # lock out the proxy.
        assert is_trusted_peer("172.30.32.2", refreshed) is True

    def test_refresh_does_not_affect_literal_entries(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        refreshed = refresh_trusted_proxies(trusted)

        assert refreshed.literal_networks == trusted.literal_networks
        assert is_trusted_peer("192.168.1.10", refreshed) is True

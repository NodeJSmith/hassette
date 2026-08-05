"""Unit tests for web API auth token resolution: explicit config, existing token file,
freshly generated token, corrupt-file recovery, and distinct per-branch logging.

Also covers ``trusted_proxies`` peer matching: IP/CIDR/hostname parsing, DNS resolution,
periodic refresh, and the peer-match function's header-free signature.

Also covers bearer-token/session-cookie auth: timing-safe bearer check, stateless HMAC-derived
cookie mint/verify with TTL enforcement, the cookie ``Secure``-flag decision (reusing the
trusted-peer matcher), and the sliding-renewal predicate.
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
from starlette.datastructures import Headers

from hassette.config.models import WebApiConfig
from hassette.exceptions import AuthTokenWriteError, TrustedProxyConfigError
from hassette.test_utils import make_addrinfo
from hassette.web.auth import (
    TOKEN_FILENAME,
    check_bearer_token,
    extract_bearer_token,
    is_trusted_peer,
    mint_session_cookie,
    refresh_trusted_proxies,
    resolve_auth_token,
    resolve_trusted_proxies,
    should_renew_session_cookie,
    should_set_secure_cookie_flag,
    verify_session_cookie,
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

    @pytest.mark.parametrize("blank_value", ["", "   ", "\t\n"])
    def test_blank_configured_token_falls_back_to_generation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, blank_value: str
    ) -> None:
        config = _make_config(auth_token=SecretStr(blank_value))

        with caplog.at_level("INFO", logger="hassette.web.auth"):
            token = resolve_auth_token(config, tmp_path)

        assert token != blank_value
        assert len(token) > 32  # secrets.token_urlsafe(32) produces a 43-char string
        assert (tmp_path / TOKEN_FILENAME).exists()

        messages = [r.message for r in caplog.records]
        assert any("blank" in m.lower() for m in messages), messages
        assert any("generated" in m.lower() for m in messages), messages


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
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[make_addrinfo("172.30.32.2")]):
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
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[make_addrinfo("172.30.32.2")]):
            trusted = resolve_trusted_proxies(("proxy.internal",))
        assert is_trusted_peer("172.30.32.2", trusted) is True

        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[make_addrinfo("172.30.32.9")]):
            refreshed = refresh_trusted_proxies(trusted)

        assert is_trusted_peer("172.30.32.9", refreshed) is True
        assert is_trusted_peer("172.30.32.2", refreshed) is False

    def test_transient_refresh_failure_keeps_last_known_good_address(self) -> None:
        with patch("hassette.web.auth.socket.getaddrinfo", return_value=[make_addrinfo("172.30.32.2")]):
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


class TestCheckBearerToken:
    def test_correct_token_succeeds(self) -> None:
        assert check_bearer_token("the-real-token", "the-real-token") is True

    def test_incorrect_token_fails(self) -> None:
        assert check_bearer_token("wrong-token", "the-real-token") is False

    def test_none_resolved_token_never_authenticates(self) -> None:
        """A None resolved_token must return False without raising — compare_digest(x, None)
        raises TypeError, which would surface as an unhandled 500 rather than an intended 401.
        """
        assert check_bearer_token("some-token", None) is False

    def test_none_presented_token_never_authenticates(self) -> None:
        assert check_bearer_token(None, "the-real-token") is False

    def test_both_none_never_authenticates(self) -> None:
        assert check_bearer_token(None, None) is False

    def test_uses_timing_safe_comparison_not_equality(self) -> None:
        """Inspect the implementation directly: secrets.compare_digest must be called, not `==`."""
        with patch("hassette.web.auth.secrets.compare_digest", return_value=True) as mock_compare:
            result = check_bearer_token("a", "b")

        mock_compare.assert_called_once_with("a", "b")
        assert result is True

    def test_non_ascii_presented_token_never_authenticates(self) -> None:
        """secrets.compare_digest raises TypeError on non-ASCII str input, not just None. ASGI
        servers decode HTTP header bytes via latin-1, so any byte >= 0x80 in a client-supplied
        Authorization header produces a non-ASCII presented value — this must degrade to False,
        not raise.
        """
        assert check_bearer_token("wrong-token\xff", "the-real-token") is False


class TestExtractBearerToken:
    """Shared by DefaultDenyMiddleware (request.headers) and authorize_ws (websocket.headers) —
    both are the same Starlette Headers type, so one parser serves both call sites.
    """

    def test_valid_bearer_header_extracts_token(self) -> None:
        headers = Headers({"authorization": "Bearer the-real-token"})
        assert extract_bearer_token(headers) == "the-real-token"

    def test_missing_header_returns_none(self) -> None:
        assert extract_bearer_token(Headers({})) is None

    def test_wrong_scheme_returns_none(self) -> None:
        headers = Headers({"authorization": "Basic the-real-token"})
        assert extract_bearer_token(headers) is None

    def test_empty_token_returns_none(self) -> None:
        headers = Headers({"authorization": "Bearer "})
        assert extract_bearer_token(headers) is None

    def test_scheme_match_is_case_insensitive(self) -> None:
        headers = Headers({"authorization": "bearer the-real-token"})
        assert extract_bearer_token(headers) == "the-real-token"


class TestSessionCookieMintAndVerify:
    def test_minted_cookie_verifies_against_same_token(self) -> None:
        token = "the-real-token"

        cookie_value = mint_session_cookie(token)
        issued_at = verify_session_cookie(cookie_value, token, session_ttl=3600)

        assert issued_at is not None

    def test_verify_is_stateless_across_fresh_calls(self) -> None:
        """Minting and verifying must not depend on any server-side state — verify must succeed
        given only the token and cookie value, as if called from a fresh process with no prior
        mint call in memory.
        """
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)

        # Simulate a "fresh process": nothing but the plain string values survives here.
        replayed_cookie_value = str(cookie_value)
        replayed_token = str(token)

        assert verify_session_cookie(replayed_cookie_value, replayed_token, session_ttl=3600) is not None

    def test_cookie_minted_for_one_token_does_not_verify_against_another(self) -> None:
        cookie_value = mint_session_cookie("token-a")

        assert verify_session_cookie(cookie_value, "token-b", session_ttl=3600) is None

    def test_malformed_cookie_value_does_not_verify(self) -> None:
        assert verify_session_cookie("not-a-valid-cookie-shape", "the-real-token", session_ttl=3600) is None

    def test_tampered_signature_does_not_verify(self) -> None:
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)
        session_id, issued_at, _signature = cookie_value.split(".")
        tampered = f"{session_id}.{issued_at}.deadbeef"

        assert verify_session_cookie(tampered, token, session_ttl=3600) is None

    def test_none_cookie_value_never_authenticates(self) -> None:
        assert verify_session_cookie(None, "the-real-token", session_ttl=3600) is None

    def test_none_resolved_token_never_authenticates(self) -> None:
        """A None resolved_token must return None without raising."""
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)

        assert verify_session_cookie(cookie_value, None, session_ttl=3600) is None

    def test_uses_timing_safe_comparison_for_signature(self) -> None:
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)

        with patch("hassette.web.auth.secrets.compare_digest", return_value=True) as mock_compare:
            result = verify_session_cookie(cookie_value, token, session_ttl=3600)

        mock_compare.assert_called_once()
        assert result is not None

    def test_non_ascii_signature_never_authenticates(self) -> None:
        """secrets.compare_digest raises TypeError on non-ASCII str input, not just None. ASGI
        servers decode HTTP header bytes via latin-1, so any byte >= 0x80 in a client-supplied
        Cookie header produces a non-ASCII signature segment — this must degrade to None, not
        raise.
        """
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)
        session_id, issued_at, _signature = cookie_value.split(".")
        mangled = f"{session_id}.{issued_at}.deadbeef\xff"

        assert verify_session_cookie(mangled, token, session_ttl=3600) is None


class TestSessionCookieTtl:
    def test_cookie_within_ttl_is_accepted(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        # 1000 seconds later, well within a 3600-second TTL.
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 1000):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at == 1_000_000

    def test_cookie_past_ttl_is_rejected(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        # 3601 seconds later, one second past a 3600-second TTL.
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 3601):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at is None

    def test_cookie_exactly_at_ttl_boundary_is_accepted(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 3600):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at == 1_000_000


class TestShouldSetSecureCookieFlag:
    def test_trusted_peer_with_https_forwarded_proto_returns_true(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "https", trusted) is True

    def test_trusted_peer_with_http_forwarded_proto_returns_false(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "http", trusted) is False

    def test_trusted_peer_with_no_forwarded_proto_returns_false(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", None, trusted) is False

    def test_untrusted_peer_returns_false_regardless_of_forwarded_proto(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("203.0.113.4", "https", trusted) is False

    def test_forwarded_proto_check_is_case_insensitive(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "HTTPS", trusted) is True

    def test_none_client_address_returns_false(self) -> None:
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag(None, "https", trusted) is False

    def test_calls_is_trusted_peer_rather_than_reimplementing_peer_matching(self) -> None:
        """Confirm the Secure-flag decision delegates to the shared trusted-peer matcher
        instead of a second, parallel IP/CIDR comparison.
        """
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        with patch("hassette.web.auth.is_trusted_peer", return_value=True) as mock_is_trusted:
            should_set_secure_cookie_flag("203.0.113.4", "https", trusted)

        mock_is_trusted.assert_called_once_with("203.0.113.4", trusted)

    def test_untrusted_peer_forwarded_proto_header_value_never_consulted(self) -> None:
        """An untrusted peer's X-Forwarded-Proto must not even be read -- confirmed here by
        patching is_trusted_peer to return False and asserting the outcome is False regardless
        of how "convincing" the header value is.
        """
        trusted = resolve_trusted_proxies(("192.168.1.10",))

        with patch("hassette.web.auth.is_trusted_peer", return_value=False):
            assert should_set_secure_cookie_flag("203.0.113.4", "https", trusted) is False


class TestShouldRenewSessionCookie:
    def test_freshly_minted_cookie_is_not_renewed(self) -> None:
        assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

    def test_past_half_life_is_renewed(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 1801):
            # 1801 seconds elapsed, session_ttl=3600 -> half-life is 1800.
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is True

    def test_exactly_at_half_life_is_renewed(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 1800):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is True

    def test_just_before_half_life_is_not_renewed(self) -> None:
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 1799):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

    def test_past_full_ttl_is_not_renewed(self) -> None:
        """A cookie already past full session_ttl is rejected by verify_session_cookie in the
        real request flow, so should_renew_session_cookie is never reached for it there. This
        function still has its own upper bound (independent of verify) so a caller holding an
        issued_at value without a fresh verify call gets "not renewed" rather than "renewed" for
        an already-expired timestamp.
        """
        with patch("hassette.web.auth._current_timestamp", return_value=1_000_000 + 3601):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

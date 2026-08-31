"""Unit tests for bearer-token/session-cookie auth: timing-safe bearer check, stateless
HMAC-derived cookie mint/verify with TTL enforcement, the cookie ``Secure``-flag decision
(reusing the trusted-peer matcher), and the sliding-renewal predicate.
"""

from unittest.mock import patch

from starlette.datastructures import Headers

from hassette.web.auth.session import (
    check_bearer_token,
    extract_bearer_token,
    mint_session_cookie,
    should_renew_session_cookie,
    should_set_secure_cookie_flag,
    verify_session_cookie,
)
from hassette.web.auth.trusted_proxies import resolve_trusted_proxies


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
        with patch("hassette.web.auth.session.secrets.compare_digest", return_value=True) as mock_compare:
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

        with patch("hassette.web.auth.session.secrets.compare_digest", return_value=True) as mock_compare:
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
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        # 1000 seconds later, well within a 3600-second TTL.
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 1000):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at == 1_000_000

    def test_cookie_past_ttl_is_rejected(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        # 3601 seconds later, one second past a 3600-second TTL.
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 3601):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at is None

    def test_cookie_exactly_at_ttl_boundary_is_accepted(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000):
            cookie_value = mint_session_cookie("the-real-token")

        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 3600):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=3600)

        assert issued_at == 1_000_000


class TestShouldSetSecureCookieFlag:
    async def test_trusted_peer_with_https_forwarded_proto_returns_true(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "https", trusted) is True

    async def test_trusted_peer_with_http_forwarded_proto_returns_false(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "http", trusted) is False

    async def test_trusted_peer_with_no_forwarded_proto_returns_false(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", None, trusted) is False

    async def test_untrusted_peer_returns_false_regardless_of_forwarded_proto(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("203.0.113.4", "https", trusted) is False

    async def test_forwarded_proto_check_is_case_insensitive(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag("192.168.1.10", "HTTPS", trusted) is True

    async def test_none_client_address_returns_false(self) -> None:
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        assert should_set_secure_cookie_flag(None, "https", trusted) is False

    async def test_calls_is_trusted_peer_rather_than_reimplementing_peer_matching(self) -> None:
        """Confirm the Secure-flag decision delegates to the shared trusted-peer matcher
        instead of a second, parallel IP/CIDR comparison.
        """
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        with patch("hassette.web.auth.session.is_trusted_peer", return_value=True) as mock_is_trusted:
            should_set_secure_cookie_flag("203.0.113.4", "https", trusted)

        mock_is_trusted.assert_called_once_with("203.0.113.4", trusted)

    async def test_untrusted_peer_forwarded_proto_header_value_never_consulted(self) -> None:
        """An untrusted peer's X-Forwarded-Proto must not even be read -- confirmed here by
        patching is_trusted_peer to return False and asserting the outcome is False regardless
        of how "convincing" the header value is.
        """
        trusted = await resolve_trusted_proxies(("192.168.1.10",))

        with patch("hassette.web.auth.session.is_trusted_peer", return_value=False):
            assert should_set_secure_cookie_flag("203.0.113.4", "https", trusted) is False


class TestShouldRenewSessionCookie:
    def test_freshly_minted_cookie_is_not_renewed(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 5):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

    def test_past_half_life_is_renewed(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 1801):
            # 1801 seconds elapsed, session_ttl=3600 -> half-life is 1800.
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is True

    def test_exactly_at_half_life_is_renewed(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 1800):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is True

    def test_just_before_half_life_is_not_renewed(self) -> None:
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 1799):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

    def test_past_full_ttl_is_not_renewed(self) -> None:
        """A cookie already past full session_ttl is rejected by verify_session_cookie in the
        real request flow, so should_renew_session_cookie is never reached for it there. This
        function still has its own upper bound (independent of verify) so a caller holding an
        issued_at value without a fresh verify call gets "not renewed" rather than "renewed" for
        an already-expired timestamp.
        """
        with patch("hassette.web.auth.session._current_timestamp", return_value=1_000_000 + 3601):
            assert should_renew_session_cookie(issued_at=1_000_000, session_ttl=3600) is False

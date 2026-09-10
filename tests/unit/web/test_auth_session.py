"""Unit tests for bearer-token/session-cookie auth: timing-safe bearer check, stateless
HMAC-derived cookie mint/verify with TTL enforcement, the cookie ``Secure``-flag decision
(reusing the trusted-peer matcher), and the sliding-renewal predicate.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
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

CLOCK_PATCH_TARGET = "hassette.web.auth.session._current_timestamp"
BASE_EPOCH = 1_000_000
"""Unix timestamp every test treats as t=0, the moment a cookie under test was minted."""

SESSION_TTL = 3600
"""Session lifetime every test in this file mints and verifies against."""

HALF_LIFE = SESSION_TTL // 2
"""Age at which ``should_renew_session_cookie`` starts renewing, per its half-life rule."""


@contextmanager
def frozen_clock(elapsed: int) -> Iterator[None]:
    """Freeze the session module's clock at ``BASE_EPOCH + elapsed`` whole unix seconds."""
    with patch(CLOCK_PATCH_TARGET, return_value=BASE_EPOCH + elapsed):
        yield


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
        issued_at = verify_session_cookie(cookie_value, token, session_ttl=SESSION_TTL)

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

        assert verify_session_cookie(replayed_cookie_value, replayed_token, session_ttl=SESSION_TTL) is not None

    def test_cookie_minted_for_one_token_does_not_verify_against_another(self) -> None:
        cookie_value = mint_session_cookie("token-a")

        assert verify_session_cookie(cookie_value, "token-b", session_ttl=SESSION_TTL) is None

    def test_malformed_cookie_value_does_not_verify(self) -> None:
        assert verify_session_cookie("not-a-valid-cookie-shape", "the-real-token", session_ttl=SESSION_TTL) is None

    def test_tampered_signature_does_not_verify(self) -> None:
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)
        session_id, issued_at, _signature = cookie_value.split(".")
        tampered = f"{session_id}.{issued_at}.deadbeef"

        assert verify_session_cookie(tampered, token, session_ttl=SESSION_TTL) is None

    def test_none_cookie_value_never_authenticates(self) -> None:
        assert verify_session_cookie(None, "the-real-token", session_ttl=SESSION_TTL) is None

    def test_none_resolved_token_never_authenticates(self) -> None:
        """A None resolved_token must return None without raising."""
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)

        assert verify_session_cookie(cookie_value, None, session_ttl=SESSION_TTL) is None

    def test_uses_timing_safe_comparison_for_signature(self) -> None:
        token = "the-real-token"
        cookie_value = mint_session_cookie(token)

        with patch("hassette.web.auth.session.secrets.compare_digest", return_value=True) as mock_compare:
            result = verify_session_cookie(cookie_value, token, session_ttl=SESSION_TTL)

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

        assert verify_session_cookie(mangled, token, session_ttl=SESSION_TTL) is None


class TestSessionCookieTtl:
    @pytest.mark.parametrize(
        ("elapsed", "expected_issued_at"),
        [
            pytest.param(1000, BASE_EPOCH, id="within_ttl_accepted"),
            # The TTL bound is inclusive — expiry is `elapsed > session_ttl`, not `>=`.
            pytest.param(SESSION_TTL, BASE_EPOCH, id="exactly_at_ttl_boundary_accepted"),
            pytest.param(SESSION_TTL + 1, None, id="past_ttl_rejected"),
        ],
    )
    def test_cookie_ttl_enforcement(self, elapsed: int, expected_issued_at: int | None) -> None:
        # The cookie is always minted at t=0; `elapsed` is how far past minting it is verified.
        with frozen_clock(0):
            cookie_value = mint_session_cookie("the-real-token")

        with frozen_clock(elapsed):
            issued_at = verify_session_cookie(cookie_value, "the-real-token", session_ttl=SESSION_TTL)

        assert issued_at == expected_issued_at


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
    @pytest.mark.parametrize(
        ("elapsed", "expected_renewed"),
        [
            pytest.param(5, False, id="freshly_minted_not_renewed"),
            pytest.param(HALF_LIFE - 1, False, id="just_before_half_life_not_renewed"),
            pytest.param(HALF_LIFE, True, id="exactly_at_half_life_renewed"),
            pytest.param(HALF_LIFE + 1, True, id="past_half_life_renewed"),
            # A cookie already past full session_ttl is rejected by verify_session_cookie in the
            # real request flow, so should_renew_session_cookie is never reached for it there. This
            # function still has its own upper bound (independent of verify) so a caller holding an
            # issued_at value without a fresh verify call gets "not renewed" rather than "renewed"
            # for an already-expired timestamp.
            pytest.param(SESSION_TTL + 1, False, id="past_full_ttl_not_renewed"),
        ],
    )
    def test_renewal_window(self, elapsed: int, expected_renewed: bool) -> None:
        with frozen_clock(elapsed):
            assert should_renew_session_cookie(issued_at=BASE_EPOCH, session_ttl=SESSION_TTL) is expected_renewed

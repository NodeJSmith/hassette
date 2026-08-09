"""Unit tests for the web API's default-deny auth gate composition: ``authorize_ws``'s
precedence between a presented bearer token, trusted-peer match, and a session cookie.
"""

import ipaddress
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.datastructures import Headers

from hassette.web.auth import authorize_ws
from hassette.web.auth.session import SESSION_COOKIE_NAME, mint_session_cookie
from hassette.web.auth.trusted_proxies import EMPTY_TRUSTED_PROXY_SET, TrustedProxySet

_WS_TEST_TOKEN = "the-real-token"
_WS_TRUSTED_PEER_IP = "203.0.113.5"
_WS_UNTRUSTED_PEER_IP = "198.51.100.9"
_WS_TRUSTED_SET = TrustedProxySet(
    literal_networks=frozenset({ipaddress.ip_network(_WS_TRUSTED_PEER_IP)}),
    hostname_entries={},
)


def _make_websocket(
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    client_host: str | None = None,
    trusted: TrustedProxySet = EMPTY_TRUSTED_PROXY_SET,
    resolved_token: str | None = _WS_TEST_TOKEN,
    session_ttl: int = 3600,
    auth_enabled: bool = True,
) -> MagicMock:
    """Build the minimal WebSocket stand-in ``authorize_ws`` reads.

    ``trusted_proxies`` and ``auth_token`` are set explicitly rather than left to the MagicMock:
    ``authorize_ws`` reaches both through ``getattr(state, ..., None)``, and an auto-generated
    Mock attribute is truthy, so an unset one would silently stand in for a real trusted set.
    """
    ws = MagicMock()
    ws.app.state.trusted_proxies = trusted
    ws.app.state.auth_token = resolved_token
    ws.app.state.hassette.config.web_api.auth_enabled = auth_enabled
    ws.app.state.hassette.config.web_api.session_ttl = session_ttl
    ws.headers = Headers(headers or {})
    ws.cookies = cookies or {}
    ws.client = SimpleNamespace(host=client_host) if client_host is not None else None
    return ws


@pytest.fixture(autouse=True)
def _propagate_hassette_logger() -> None:
    """Ensure the "hassette" logger propagates so caplog can see records.

    Some other test in the session may have left ``propagate`` set to False (e.g. via
    ``enable_basic_logging()``); caplog relies on propagation to the root logger. Same
    workaround as ``tests/unit/test_autodetect_apps.py``.
    """
    logging.getLogger("hassette").propagate = True


class TestAuthorizeWsPrecedence:
    """`authorize_ws` applies the identical precedence `DefaultDenyMiddleware` applies to HTTP:
    a presented `Authorization` header is always validated and fails closed, and peer trust
    covers only a handshake that presents no header at all.

    Non-browser clients (CLI, scripts) attach `Authorization: Bearer <token>` at WebSocket connect
    time, so the same forward-auth-proxy deployment that motivates the HTTP ordering reaches this
    function too. Divergence between the two would leave the WS handshake as the bypass.
    """

    def test_correct_bearer_token_from_trusted_peer_accepts(self) -> None:
        ws = _make_websocket(
            headers={"authorization": f"Bearer {_WS_TEST_TOKEN}"},
            client_host=_WS_TRUSTED_PEER_IP,
            trusted=_WS_TRUSTED_SET,
        )

        assert authorize_ws(ws) is True

    def test_wrong_bearer_token_from_trusted_peer_rejects(self) -> None:
        ws = _make_websocket(
            headers={"authorization": "Bearer wrong-token"},
            client_host=_WS_TRUSTED_PEER_IP,
            trusted=_WS_TRUSTED_SET,
        )

        assert authorize_ws(ws) is False

    def test_unrecognized_scheme_from_trusted_peer_rejects(self) -> None:
        ws = _make_websocket(
            headers={"authorization": f"Basic {_WS_TEST_TOKEN}"},
            client_host=_WS_TRUSTED_PEER_IP,
            trusted=_WS_TRUSTED_SET,
        )

        assert authorize_ws(ws) is False

    def test_empty_bearer_value_from_trusted_peer_rejects(self) -> None:
        ws = _make_websocket(
            headers={"authorization": "Bearer "},
            client_host=_WS_TRUSTED_PEER_IP,
            trusted=_WS_TRUSTED_SET,
        )

        assert authorize_ws(ws) is False

    def test_no_authorization_header_from_trusted_peer_accepts(self) -> None:
        ws = _make_websocket(client_host=_WS_TRUSTED_PEER_IP, trusted=_WS_TRUSTED_SET)

        assert authorize_ws(ws) is True

    def test_untrusted_peer_with_correct_bearer_token_accepts(self) -> None:
        ws = _make_websocket(headers={"authorization": f"Bearer {_WS_TEST_TOKEN}"}, client_host=_WS_UNTRUSTED_PEER_IP)

        assert authorize_ws(ws) is True

    def test_untrusted_peer_with_valid_cookie_accepts(self) -> None:
        """The browser path: no `Authorization` header, no peer match, valid session cookie."""
        ws = _make_websocket(
            cookies={SESSION_COOKIE_NAME: mint_session_cookie(_WS_TEST_TOKEN)},
            client_host=_WS_UNTRUSTED_PEER_IP,
        )

        assert authorize_ws(ws) is True

    def test_wrong_bearer_token_does_not_fall_back_to_valid_cookie(self) -> None:
        ws = _make_websocket(
            headers={"authorization": "Bearer wrong-token"},
            cookies={SESSION_COOKIE_NAME: mint_session_cookie(_WS_TEST_TOKEN)},
            client_host=_WS_UNTRUSTED_PEER_IP,
        )

        assert authorize_ws(ws) is False

    def test_untrusted_peer_with_no_credential_rejects(self) -> None:
        ws = _make_websocket(client_host=_WS_UNTRUSTED_PEER_IP)

        assert authorize_ws(ws) is False

    def test_auth_disabled_accepts_a_wrong_bearer_token(self) -> None:
        """`auth_enabled=False` short-circuits before any of the above, unchanged."""
        ws = _make_websocket(
            headers={"authorization": "Bearer wrong-token"},
            client_host=_WS_UNTRUSTED_PEER_IP,
            auth_enabled=False,
        )

        assert authorize_ws(ws) is True

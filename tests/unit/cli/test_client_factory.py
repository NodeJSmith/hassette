"""Tests for ``open_client``: how the CLI's resolved target and credential reach the wire."""

import base64
from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from hassette_client import HassetteClient
from yarl import URL

from hassette.cli.client_factory import open_client
from hassette.cli.target import ResolvedCredential, ServerTarget

HEALTH_BODY = {
    "status": "ok",
    "websocket_connected": True,
    "bootstrap_released": True,
    "uptime_seconds": 1.0,
    "entity_count": 0,
    "app_count": 0,
    "version": "0.0.0-test",
}
TOKEN = "cli-token"


class AuthRecordingServer:
    """Answers every request with a healthy status and records its ``Authorization`` header."""

    def __init__(self) -> None:
        self.base_url = ""
        self.authorization: list[str | None] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.authorization.append(request.headers.get("Authorization"))
        return web.json_response(HEALTH_BODY)


@pytest.fixture
async def server() -> AsyncIterator[AuthRecordingServer]:
    recorder = AuthRecordingServer()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", recorder.handle)
    async with TestServer(app) as test_server:
        recorder.base_url = str(test_server.make_url("")).rstrip("/")
        yield recorder


def make_target(base_url: str, *, verify_ssl: bool = True) -> ServerTarget:
    return ServerTarget(base_url=base_url, is_loopback=True, verify_ssl=verify_ssl)


def session_of(client: HassetteClient) -> aiohttp.ClientSession:
    return client._transport.session  # pyright: ignore[reportPrivateUsage]


async def test_userinfo_target_sends_basic_auth(server: AuthRecordingServer) -> None:
    base_url = str(URL(server.base_url).with_user("alice").with_password("s3cret"))

    async with open_client(make_target(base_url), None) as client:
        await client.get_health()

    expected = base64.b64encode(b"alice:s3cret").decode()
    assert server.authorization == [f"Basic {expected}"]


async def test_credential_sends_bearer_token(server: AuthRecordingServer) -> None:
    credential = ResolvedCredential(token=TOKEN, source="cli.auth_token")

    async with open_client(make_target(server.base_url), credential) as client:
        await client.get_health()

    assert server.authorization == [f"Bearer {TOKEN}"]


async def test_no_credential_sends_no_authorization(server: AuthRecordingServer) -> None:
    async with open_client(make_target(server.base_url), None) as client:
        await client.get_health()

    assert server.authorization == [None]


@pytest.mark.parametrize(("verify_ssl", "expected_ssl"), [(False, False), (True, True)])
async def test_verify_ssl_sets_connector_ssl(verify_ssl: bool, expected_ssl: bool) -> None:
    async with open_client(make_target("https://example.com", verify_ssl=verify_ssl), None) as client:
        connector = session_of(client).connector
        assert isinstance(connector, aiohttp.TCPConnector)
        assert connector._ssl is expected_ssl  # pyright: ignore[reportPrivateUsage]


async def test_session_closed_after_exit() -> None:
    async with open_client(make_target("http://127.0.0.1:8126"), None) as client:
        session = session_of(client)
        assert not session.closed

    assert session.closed


async def test_session_closed_when_body_raises() -> None:
    sessions: list[aiohttp.ClientSession] = []

    async def use_and_fail() -> None:
        async with open_client(make_target("http://127.0.0.1:8126"), None) as client:
            sessions.append(session_of(client))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await use_and_fail()

    assert sessions[0].closed

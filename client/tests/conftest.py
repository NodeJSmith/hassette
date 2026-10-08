"""Fixtures for client tests: a fake server and a client wired to it over a real socket.

HTTP is the client's boundary, so tests run real requests rather than mocking the session.
"""

from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fake_server import TEST_TOKEN, FakeServer
from hassette_client import HassetteClient


@pytest.fixture
async def server() -> AsyncIterator[FakeServer]:
    fake = FakeServer()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    app.on_response_prepare.append(fake.strip_default_content_type)
    async with TestServer(app) as test_server:
        fake.base_url = str(test_server.make_url("")).rstrip("/")
        yield fake
        fake.released.set()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
def client(session: aiohttp.ClientSession, server: FakeServer) -> HassetteClient:
    return HassetteClient(session, server.base_url, token=TEST_TOKEN)

"""Request mechanics: session ownership, auth header, timeouts, redirects, query and path encoding."""

import json
import math

import aiohttp
import pytest
from fake_server import HEALTH_BODY, TEST_TOKEN, FakeServer
from hassette_client import (
    HassetteClient,
    HassetteConnectionError,
    HassetteTimeoutError,
    NotFoundError,
    RedirectError,
)
from hassette_wire import SystemStatusResponse
from yarl import URL


async def test_requests_use_the_callers_session_and_leave_it_open(
    session: aiohttp.ClientSession, server: FakeServer
) -> None:
    server.respond(200, HEALTH_BODY)
    client = HassetteClient(session, server.base_url)

    health = await client.get_health()
    await client.get_health()

    assert isinstance(health, SystemStatusResponse)
    assert not session.closed
    assert len(server.requests) == 2


async def test_token_is_sent_as_a_bearer_header(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, HEALTH_BODY)

    await client.get_health()

    assert server.requests[0].headers["Authorization"] == f"Bearer {TEST_TOKEN}"


async def test_no_token_sends_no_authorization_header(session: aiohttp.ClientSession, server: FakeServer) -> None:
    server.respond(200, HEALTH_BODY)

    await HassetteClient(session, server.base_url, token=None).get_health()

    assert "Authorization" not in server.requests[0].headers


async def test_empty_token_still_sends_an_authorization_header(
    session: aiohttp.ClientSession, server: FakeServer
) -> None:
    # An empty token must not fall back to the no-header path, where a trusted proxy peer would be admitted.
    server.respond(200, HEALTH_BODY)

    await HassetteClient(session, server.base_url, token="").get_health()

    assert server.requests[0].headers["Authorization"] == "Bearer "


@pytest.mark.parametrize("request_timeout", [0, -1.0, math.nan, math.inf])
def test_unusable_request_timeout_raises_value_error(
    session: aiohttp.ClientSession, server: FakeServer, request_timeout: float
) -> None:
    with pytest.raises(ValueError, match="request_timeout"):
        HassetteClient(session, server.base_url, request_timeout=request_timeout)


async def test_unanswered_request_raises_timeout_error(session: aiohttp.ClientSession, server: FakeServer) -> None:
    server.respond(200, HEALTH_BODY, hang=True)
    client = HassetteClient(session, server.base_url, request_timeout=0.05)

    with pytest.raises(HassetteTimeoutError, match=r"timed out after 0\.05s"):
        await client.get_health()


async def test_refused_connection_raises_connection_error(session: aiohttp.ClientSession) -> None:
    # Port 1 on loopback is reserved and closed, so the connect is refused at once.
    client = HassetteClient(session, "http://user:secret@127.0.0.1:1")

    with pytest.raises(HassetteConnectionError) as exc_info:
        await client.get_health()

    assert "http://127.0.0.1:1" in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, aiohttp.ClientConnectorError)


@pytest.mark.parametrize("url", ["not a url", "http://", "http://user:secret@[::1"])
async def test_malformed_base_url_raises_connection_error_without_echoing_it(
    session: aiohttp.ClientSession, url: str
) -> None:
    """An HA config flow maps HassetteConnectionError to ``cannot_connect``, so a bad URL must land there."""
    with pytest.raises(HassetteConnectionError, match="URL is invalid") as exc_info:
        await HassetteClient(session, url).get_health()

    assert "secret" not in str(exc_info.value)


async def test_closed_session_raises_aiohttps_own_error(session: aiohttp.ClientSession, server: FakeServer) -> None:
    """A closed session is a bug in the calling code, not a network failure, so it isn't wrapped."""
    client = HassetteClient(session, server.base_url)
    await session.close()

    with pytest.raises(RuntimeError, match="Session is closed"):
        await client.get_health()


async def test_control_character_in_token_raises_value_error_on_first_request(
    session: aiohttp.ClientSession, server: FakeServer
) -> None:
    client = HassetteClient(session, server.base_url, token="abc\r\nX-Injected: 1")  # noqa: S106 - a header-injection probe, not a credential

    # The type is the contract; the message varies across aiohttp releases.
    with pytest.raises(ValueError):  # noqa: PT011
        await client.get_health()

    assert server.requests == []


async def test_token_with_credentials_in_base_url_raises_value_error_on_first_request(
    session: aiohttp.ClientSession, server: FakeServer
) -> None:
    url_with_credentials = str(URL(server.base_url).with_user("user").with_password("pw"))
    client = HassetteClient(session, url_with_credentials, token=TEST_TOKEN)

    # The match pins the cause: aiohttp won't send an Authorization header alongside URL credentials.
    with pytest.raises(ValueError, match="AUTHORIZATION header"):
        await client.get_health()

    assert server.requests == []


async def test_redirect_is_raised_not_followed(client: HassetteClient, server: FakeServer) -> None:
    login = "https://auth.example.com/login"
    server.respond(302, raw=b"", content_type="text/html", headers={"Location": login})

    with pytest.raises(RedirectError) as exc_info:
        await client.get_health()

    assert exc_info.value.status == 302
    assert exc_info.value.location == login
    assert len(server.requests) == 1


async def test_unset_query_filters_are_not_sent(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, [])

    await client.get_recent_logs(limit=5, level="ERROR")

    assert server.requests[0].query == {"limit": "5", "level": "ERROR"}


async def test_path_parameters_stay_one_segment(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, raw=b"null")

    await client.get_execution("a?b#c")

    assert server.requests[0].path == "/api/telemetry/execution/a%3Fb%23c"


async def test_base_url_path_prefix_is_kept(session: aiohttp.ClientSession, server: FakeServer) -> None:
    server.respond(200, HEALTH_BODY)

    await HassetteClient(session, f"{server.base_url}/hassette/").get_health()

    assert server.requests[0].path == "/hassette/api/health"


async def test_request_body_is_sent_as_json(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, {"logger": "hassette", "effective_level": "DEBUG"})

    response = await client.set_log_level("hassette", "DEBUG")

    request = server.requests[0]
    assert (request.method, request.path) == ("PUT", "/api/logs/level")
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.body) == {"logger": "hassette", "level": "DEBUG"}
    assert response.effective_level == "DEBUG"


@pytest.mark.parametrize(
    ("instance", "expected_path"),
    [(None, "/api/apps/my_app/reload"), (2, "/api/apps/my_app/instances/2/reload")],
)
async def test_action_routes_by_instance(
    client: HassetteClient, server: FakeServer, instance: int | None, expected_path: str
) -> None:
    server.respond(202, {"app_key": "my_app", "action": "reload", "instance_index": instance})

    response = await client.action("my_app", "reload", instance=instance)

    assert (server.requests[0].method, server.requests[0].path) == ("POST", expected_path)
    assert response.instance_index == instance


async def test_action_name_is_left_to_the_server(client: HassetteClient, server: FakeServer) -> None:
    """An older client can drive an action a newer server added; an unknown one is the server's 404."""
    server.respond_problem(404, "not_found")

    with pytest.raises(NotFoundError):
        await client.action("my_app", "restart")  # pyright: ignore[reportArgumentType]

    assert server.requests[0].path == "/api/apps/my_app/restart"


@pytest.mark.parametrize("app_key", ["", ".", "..", "foo/config", "/"])
async def test_path_parameter_that_would_change_the_route_is_rejected_before_any_request(
    client: HassetteClient, server: FakeServer, app_key: str
) -> None:
    """URL normalization would turn ``/api/apps/../config`` into ``/api/config``, and the server decodes
    ``%2F`` before routing, so ``foo/config`` would reach ``/api/apps/foo/config``.
    """
    with pytest.raises(ValueError, match="path parameter"):
        await client.get_app_config(app_key)

    assert server.requests == []


@pytest.mark.parametrize("action", ["..", "../config"])
async def test_action_that_would_change_the_route_is_rejected_before_any_request(
    client: HassetteClient, server: FakeServer, action: str
) -> None:
    with pytest.raises(ValueError, match="path parameter"):
        await client.action("my_app", action)  # pyright: ignore[reportArgumentType]

    assert server.requests == []

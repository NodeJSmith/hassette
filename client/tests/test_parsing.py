"""Lenient parsing, body classification by ``Content-Type``, and the 503 status-model probes."""

import pytest
from fake_server import HEALTH_BODY, FakeServer
from hassette_client import (
    HassetteClient,
    ResponseValidationError,
    ServerError,
    ServiceUnavailableError,
    TelemetryUnavailableError,
    UnexpectedResponseError,
    parse_response,
)
from hassette_wire import Execution, ReadinessResponse, SystemStatusResponse, TelemetryStatusResponse, UnknownValue


async def test_unknown_field_is_ignored(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, {**HEALTH_BODY, "added_in_a_later_release": 1})

    health = await client.get_health()

    assert health.status == "ok"


async def test_unknown_literal_value_becomes_unknown_value(client: HassetteClient, server: FakeServer) -> None:
    server.respond(200, {**HEALTH_BODY, "status": "rebooting"})

    health = await client.get_health()

    assert isinstance(health.status, UnknownValue)
    assert health.status == "rebooting"


async def test_unknown_value_in_a_list_response_becomes_unknown_value(
    client: HassetteClient, server: FakeServer
) -> None:
    entry = {"id": 1, "seq": 1, "timestamp": 0.0, "level": "INFO", "logger_name": "x", "message": "m"}
    server.respond(200, [{**entry, "execution_kind": "webhook"}])

    logs = await client.get_recent_logs()

    assert isinstance(logs[0].execution_kind, UnknownValue)
    assert logs[0].execution_kind == "webhook"


def test_parse_response_is_strict_about_breaking_changes() -> None:
    with pytest.raises(ResponseValidationError) as exc_info:
        parse_response(SystemStatusResponse, b'{"status": "ok"}')

    assert exc_info.value.endpoint is None
    assert "websocket_connected: missing" in exc_info.value.problems


def test_parse_response_rejects_a_non_json_body() -> None:
    with pytest.raises(ResponseValidationError) as exc_info:
        parse_response(SystemStatusResponse, b"<html>login</html>")

    assert exc_info.value.problems == ["<body>: json_invalid"]


def test_parse_response_accepts_an_optional_type() -> None:
    assert parse_response(Execution | None, "null") is None


@pytest.mark.parametrize("status", [200, 503])
async def test_get_ready_returns_the_status_model_on_200_and_503(
    client: HassetteClient, server: FakeServer, status: int
) -> None:
    server.respond(status, {"status": "starting" if status == 503 else "ok", "ready": status == 200})

    readiness = await client.get_ready()

    assert isinstance(readiness, ReadinessResponse)
    assert readiness.ready is (status == 200)


@pytest.mark.parametrize("status", [200, 503])
async def test_get_telemetry_status_returns_the_status_model_on_200_and_503(
    client: HassetteClient, server: FakeServer, status: int
) -> None:
    server.respond(status, {"degraded": status == 503})

    telemetry = await client.get_telemetry_status()

    assert isinstance(telemetry, TelemetryStatusResponse)
    assert telemetry.degraded is (status == 503)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"<html>upstream down</html>", "text/html"),
        (b"upstream down", None),
        (b'{"error": "upstream connect error"}', "application/json"),
        (b'{"error": "upstream connect error"}', None),
    ],
    ids=["html", "untyped-text", "foreign-json", "untyped-foreign-json"],
)
async def test_probe_503_that_is_not_the_status_model_raises(
    client: HassetteClient, server: FakeServer, body: bytes, content_type: str | None
) -> None:
    """A 503 that doesn't parse as the probe's status model is a proxy saying hassette is down."""
    server.respond(503, raw=body, content_type=content_type)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await client.get_ready()

    assert type(exc_info.value) is ServiceUnavailableError


async def test_probe_503_without_content_type_parses_as_the_status_model(
    client: HassetteClient, server: FakeServer
) -> None:
    """A proxy that strips Content-Type still leaves "up but not ready" readable."""
    server.respond(503, raw=b'{"status": "starting", "ready": false}', content_type=None)

    ready = await client.get_ready()

    assert ready.ready is False


async def test_probe_503_problem_raises_by_its_code(client: HassetteClient, server: FakeServer) -> None:
    server.respond_problem(503, "telemetry_unavailable")

    with pytest.raises(TelemetryUnavailableError):
        await client.get_telemetry_status()


async def test_probe_non_503_error_still_raises(client: HassetteClient, server: FakeServer) -> None:
    server.respond(500, raw=b"", content_type="text/plain")

    with pytest.raises(ServerError):
        await client.get_telemetry_status()


async def test_data_route_503_raises_even_with_a_parseable_body(client: HassetteClient, server: FakeServer) -> None:
    server.respond_problem(503, "telemetry_unavailable", detail="database is locked")

    with pytest.raises(TelemetryUnavailableError) as exc_info:
        await client.get_app_grid()

    assert exc_info.value.detail == "database is locked"


@pytest.mark.parametrize("content_type", ["text/html", "application/problem+json", "application/octet-stream"])
async def test_2xx_body_that_isnt_json_raises_unexpected_response(
    client: HassetteClient, server: FakeServer, content_type: str
) -> None:
    """A proxy login page, or the web UI's HTML at a wrong base_url, didn't come from the API."""
    page = b"<html>Sign in</html>"
    server.respond(200, raw=page, content_type=f"{content_type}; charset=utf-8")

    with pytest.raises(UnexpectedResponseError) as exc_info:
        await client.get_health()

    error = exc_info.value
    assert isinstance(error, ResponseValidationError)
    assert (error.status, error.content_type) == (200, content_type)
    assert error.problems == [f"<body>: not_json ({content_type})"]
    assert error.body_excerpt == page.decode()
    assert "Sign in" not in str(error)
    assert "check base_url, or whether a proxy answered" in str(error)


@pytest.mark.parametrize(
    "content_type", [None, "application/json", "Application/JSON; charset=utf-8", "application/vnd.x+json"]
)
async def test_2xx_json_or_untyped_body_is_parsed(
    client: HassetteClient, server: FakeServer, content_type: str | None
) -> None:
    """A proxy that strips ``Content-Type`` falls back to parsing the body."""
    server.respond(200, HEALTH_BODY, content_type=content_type)

    health = await client.get_health()

    assert health.version == HEALTH_BODY["version"]


async def test_response_validation_error_records_the_response(client: HassetteClient, server: FakeServer) -> None:
    server.respond(202, {"job_id": "not-an-int"}, content_type="application/json")

    with pytest.raises(ResponseValidationError) as exc_info:
        await client.trigger_job(1)

    error = exc_info.value
    assert type(error) is ResponseValidationError
    assert (error.status, error.content_type) == (202, "application/json")


async def test_one_invalid_list_element_fails_the_whole_response(client: HassetteClient, server: FakeServer) -> None:
    entry = {"id": 1, "seq": 1, "timestamp": 0.0, "level": "INFO", "logger_name": "x", "message": "m"}
    server.respond(200, [entry, {**entry, "seq": "not-a-number"}])

    with pytest.raises(ResponseValidationError) as exc_info:
        await client.get_recent_logs()

    assert exc_info.value.problems == ["1.seq: int_parsing"]


async def test_empty_liveness_body_isnt_live(client: HassetteClient, server: FakeServer) -> None:
    """Any server answering ``{}`` would otherwise count as a live hassette."""
    server.respond(200, {})

    with pytest.raises(ResponseValidationError):
        await client.get_liveness()


@pytest.mark.parametrize(
    ("call", "body"),
    [
        ("get_liveness", {"status": "draining"}),
        ("action", {"status": "queued", "app_key": "a", "action": "start", "instance_index": None}),
        ("trigger_job", {"status": "queued", "job_id": 1, "job_name": "j"}),
    ],
)
async def test_new_status_value_from_a_newer_server_is_tolerated(
    client: HassetteClient, server: FakeServer, call: str, body: dict[str, object]
) -> None:
    """A write has already happened by the time its status parses, so a new status value can't fail it."""
    server.respond(200, body)
    calls = {
        "get_liveness": client.get_liveness,
        "action": lambda: client.action("a", "start"),
        "trigger_job": lambda: client.trigger_job(1),
    }

    response = await calls[call]()

    assert isinstance(response.status, UnknownValue)

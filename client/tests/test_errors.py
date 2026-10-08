"""Error responses: every branch of code → status → family resolution, messages, and copy/pickle."""

import copy
import pickle
from collections.abc import Callable

import pytest
from fake_server import FakeServer
from hassette_client import (
    AppNotFoundError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    GatewayError,
    HassetteClient,
    HassetteClientError,
    HassetteConnectionError,
    HassetteHTTPError,
    HassetteTimeoutError,
    NotFoundError,
    RedirectError,
    RequestValidationError,
    ResponseValidationError,
    ServerError,
    ServiceUnavailableError,
    UnexpectedResponseError,
    UnsupportedServerVersionError,
)
from hassette_client.errors import CODE_ERRORS, GENERIC_CODES, STATUS_ERRORS
from hassette_client.transport import MAX_BODY_EXCERPT_BYTES, MAX_ERROR_BODY_BYTES
from hassette_wire import ProblemCode, ProblemDetail, UnknownValue

CODE_STATUS: dict[ProblemCode, int] = {
    ProblemCode.INVALID_APP_KEY: 400,
    ProblemCode.APP_NOT_FOUND: 404,
    ProblemCode.INSTANCE_NOT_FOUND: 404,
    ProblemCode.BOOTSTRAP_NOT_RELEASED: 409,
    ProblemCode.APP_BLOCKED: 409,
    ProblemCode.ACTION_FAILED: 500,
    ProblemCode.TELEMETRY_UNAVAILABLE: 503,
    ProblemCode.SOURCE_NOT_FOUND: 404,
    ProblemCode.PATH_TRAVERSAL: 403,
    ProblemCode.SOURCE_UNAVAILABLE: 500,
    ProblemCode.JOB_NOT_REGISTERED: 409,
}
"""The status the server sends each class-mapped code with."""

PROBLEM = ProblemDetail.model_validate(
    {"title": "Not Found", "status": 404, "detail": "no such app", "code": "app_not_found"}
)

PICKLABLE_ERRORS: list[HassetteClientError] = [
    HassetteConnectionError("GET /api/health to http://h failed"),
    HassetteTimeoutError("GET /api/health to http://h timed out after 10.0s"),
    ResponseValidationError(
        model="AppSummary", endpoint="GET /api/apps/a", problems=["status: missing"], status=200, content_type="a/json"
    ),
    ResponseValidationError(model="AppSummary", endpoint=None, problems=["<body>: json_invalid"]),
    UnexpectedResponseError(
        model="AppSummary",
        endpoint="GET /api/apps/a",
        status=200,
        content_type="text/html",
        body_size=12,
        body_excerpt="<html></html",
    ),
    UnsupportedServerVersionError(server_version="0.50.0", min_version="0.55.0"),
    AppNotFoundError(status=404, endpoint="GET /api/apps/a", problem=PROBLEM),
    RedirectError(
        status=302,
        endpoint="GET /api/health",
        problem=None,
        content_type="text/html",
        body_size=5000,
        body_truncated=True,
        body_excerpt="<html>",
        location="https://auth.example.com/login",
    ),
]


def test_every_problem_code_is_either_mapped_or_deliberately_generic() -> None:
    """A code added on the server fails here until the client decides how to surface it."""
    mapped = set(CODE_ERRORS)

    assert mapped.isdisjoint(GENERIC_CODES)
    assert mapped | GENERIC_CODES == set(ProblemCode)


def test_code_classes_specialize_their_status_class() -> None:
    """``except NotFoundError`` must still catch ``AppNotFoundError``, and so on for every code class."""
    for code, error_class in CODE_ERRORS.items():
        status = CODE_STATUS[code]
        family = STATUS_ERRORS.get(status, ServerError)
        assert issubclass(error_class, family), (code, error_class, family)


@pytest.mark.parametrize(("code", "error_class"), list(CODE_ERRORS.items()))
async def test_problem_code_raises_its_class(
    client: HassetteClient, server: FakeServer, code: ProblemCode, error_class: type[HassetteHTTPError]
) -> None:
    server.respond_problem(CODE_STATUS[code], code.value, detail="specific detail")

    with pytest.raises(error_class) as exc_info:
        await client.get_health()

    error = exc_info.value
    assert type(error) is error_class
    assert error.code == code
    assert error.detail == "specific detail"
    assert error.status == CODE_STATUS[code]
    assert error.endpoint == "GET /api/health"
    assert str(error) == f"GET /api/health returned {CODE_STATUS[code]}: specific detail"
    assert error.body_excerpt is None


@pytest.mark.parametrize(
    ("status", "code", "error_class"),
    [
        (401, ProblemCode.NOT_AUTHENTICATED, AuthenticationError),
        (401, ProblemCode.INVALID_TOKEN, AuthenticationError),
        (422, ProblemCode.VALIDATION_FAILED, RequestValidationError),
        (404, ProblemCode.NOT_FOUND, NotFoundError),
        (413, ProblemCode.BODY_TOO_LARGE, HassetteHTTPError),
        (405, ProblemCode.METHOD_NOT_ALLOWED, HassetteHTTPError),
        (400, ProblemCode.HTTP_ERROR, BadRequestError),
        (500, ProblemCode.INTERNAL_ERROR, ServerError),
    ],
)
async def test_generic_code_resolves_by_status(
    client: HassetteClient, server: FakeServer, status: int, code: ProblemCode, error_class: type[HassetteHTTPError]
) -> None:
    server.respond_problem(status, code.value)

    with pytest.raises(error_class) as exc_info:
        await client.get_health()

    assert type(exc_info.value) is error_class
    assert exc_info.value.code == code


async def test_unknown_code_from_a_newer_server_resolves_by_status(client: HassetteClient, server: FakeServer) -> None:
    server.respond_problem(409, "app_paused")

    with pytest.raises(ConflictError) as exc_info:
        await client.get_health()

    assert type(exc_info.value) is ConflictError
    assert isinstance(exc_info.value.code, UnknownValue)
    assert exc_info.value.code == "app_paused"


async def test_html_502_from_a_proxy_keeps_its_body_out_of_the_message(
    client: HassetteClient, server: FakeServer
) -> None:
    page = "<html>secret-session-id " + "x" * 1000 + "</html>"
    server.respond(502, raw=page.encode(), content_type="text/html; charset=utf-8")

    with pytest.raises(GatewayError) as exc_info:
        await client.get_health()

    error = exc_info.value
    assert error.problem is None
    assert error.code is None
    assert error.detail is None
    assert error.content_type == "text/html"
    assert error.body_excerpt == page[:MAX_BODY_EXCERPT_BYTES]
    assert str(error) == f"GET /api/health returned 502 (text/html, {len(page)} bytes)"


async def test_long_non_problem_error_body_is_read_only_up_to_the_cap(
    client: HassetteClient, server: FakeServer
) -> None:
    server.respond(502, raw=b"x" * (MAX_ERROR_BODY_BYTES * 4), content_type="text/html")

    with pytest.raises(GatewayError) as exc_info:
        await client.get_health()

    error = exc_info.value
    assert error.body_truncated
    assert error.body_size == MAX_ERROR_BODY_BYTES
    assert str(error) == f"GET /api/health returned 502 (text/html, more than {MAX_ERROR_BODY_BYTES} bytes)"


async def test_long_problem_body_is_read_whole_and_keeps_its_class(client: HassetteClient, server: FakeServer) -> None:
    """Truncating a hassette problem would make it unparseable and cost it its code-specific class."""
    detail = "y" * (MAX_ERROR_BODY_BYTES * 2)
    server.respond_problem(404, "app_not_found", detail=detail)

    with pytest.raises(AppNotFoundError) as exc_info:
        await client.get_app("my_app")

    assert exc_info.value.detail == detail
    assert not exc_info.value.body_truncated


async def test_empty_503_is_service_unavailable(client: HassetteClient, server: FakeServer) -> None:
    server.respond(503, raw=b"", content_type="text/plain")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await client.get_apps()

    assert type(exc_info.value) is ServiceUnavailableError
    assert exc_info.value.detail is None
    assert str(exc_info.value) == "GET /api/apps returned 503 (empty body)"


async def test_problem_json_without_a_hassette_code_maps_by_status(client: HassetteClient, server: FakeServer) -> None:
    """A foreign RFC 9457 body, from a proxy or gateway, isn't a hassette problem."""
    body = b'{"title": "Not Found", "status": 404}'
    server.respond(404, raw=body, content_type="application/problem+json")

    with pytest.raises(NotFoundError) as exc_info:
        await client.get_health()

    assert exc_info.value.problem is None
    assert str(exc_info.value) == (
        f"GET /api/health returned 404 (malformed problem body, application/problem+json, {len(body)} bytes)"
    )


@pytest.mark.parametrize("content_type", ["application/json", None])
async def test_json_or_untyped_error_body_maps_by_status_without_parsing_a_problem(
    client: HassetteClient, server: FakeServer, content_type: str | None
) -> None:
    """Only ``application/problem+json`` is read as a hassette problem, so a foreign JSON 409 has no code."""
    problem = {"type": "about:blank", "title": "x", "status": 409, "detail": "d", "code": "app_blocked"}
    server.respond(409, problem, content_type=content_type)

    with pytest.raises(ConflictError) as exc_info:
        await client.get_health()

    assert type(exc_info.value) is ConflictError
    assert exc_info.value.problem is None


@pytest.mark.parametrize(
    ("status", "error_class"),
    [(301, RedirectError), (307, RedirectError), (418, HassetteHTTPError), (501, ServerError), (504, GatewayError)],
)
async def test_status_family_fallback(
    client: HassetteClient, server: FakeServer, status: int, error_class: type[HassetteHTTPError]
) -> None:
    server.respond(status, raw=b"", content_type="text/plain")

    with pytest.raises(error_class) as exc_info:
        await client.get_health()

    assert type(exc_info.value) is error_class


async def test_success_body_with_a_breaking_change_raises_response_validation_error(
    client: HassetteClient, server: FakeServer
) -> None:
    server.respond(200, {"status": "ok", "websocket_connected": "secret-value"})

    with pytest.raises(ResponseValidationError) as exc_info:
        await client.get_health()

    error = exc_info.value
    assert error.model == "SystemStatusResponse"
    assert error.endpoint == "GET /api/health"
    assert "websocket_connected: bool_parsing" in error.problems
    assert "secret-value" not in str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__


def pickle_round_trip(error: HassetteClientError) -> HassetteClientError:
    return pickle.loads(pickle.dumps(error))  # noqa: S301 - the test's own freshly pickled bytes


@pytest.mark.parametrize("error", PICKLABLE_ERRORS, ids=lambda error: type(error).__name__)
@pytest.mark.parametrize("round_trip", [copy.copy, pickle_round_trip], ids=["copy", "pickle"])
def test_errors_round_trip_with_every_attribute(
    error: HassetteClientError, round_trip: Callable[[HassetteClientError], HassetteClientError]
) -> None:
    restored = round_trip(error)

    assert type(restored) is type(error)
    assert str(restored) == str(error)
    assert vars(restored) == vars(error)


def test_deep_copy_doesnt_share_mutable_attributes() -> None:
    error = ResponseValidationError(model="AppSummary", endpoint=None, problems=["status: missing"])

    copied = copy.deepcopy(error)

    assert copied.problems == error.problems
    assert copied.problems is not error.problems

"""An OpenAPI document is the oracle for what the client sends and must cover.

By default the document is the committed ``frontend/openapi.json``, the current server's API:

- a route added on the server fails ``test_every_operation_has_a_client_method`` until a method calls it,
  unless :data:`BROWSER_ONLY_OPERATIONS` names it;
- a query parameter the client misnames fails ``test_every_client_request_exists_in_the_spec``, since the
  server would silently ignore it;
- a method parsing the wrong model fails ``test_every_method_return_type_matches_its_routes_response_schema``;
- a problem code a route declares fails ``test_every_declared_problem_code_resolves`` until the client
  maps it.

With ``HASSETTE_CLIENT_OPENAPI`` set to another document, only the request checks run. On every PR,
``tools/check_client_floor.py`` points it at the ``openapi.json`` of the floor release (the oldest release
reporting ``MIN_API_SCHEMA_VERSION``), proving every request this client sends exists on the oldest server
it claims to support. The tool also sets ``HASSETTE_CLIENT_OPERATIONS``, and this module writes the
operations the client calls there, for the tool's response check.
"""

import contextlib
import inspect
import json
import os
import re
import types
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from fake_server import FakeServer
from hassette_client import HassetteClient, HassetteClientError
from hassette_client.errors import CODE_ERRORS, GENERIC_CODES, PROBLEM_MEDIA_TYPE, error_class_for
from hassette_wire import ProblemCode

OPENAPI_ENV_VAR = "HASSETTE_CLIENT_OPENAPI"

HEAD_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"

OTHER_OPENAPI = os.environ.get(OPENAPI_ENV_VAR)

OPENAPI_PATH = Path(OTHER_OPENAPI) if OTHER_OPENAPI else HEAD_OPENAPI_PATH

OPERATIONS_ENV_VAR = "HASSETTE_CLIENT_OPERATIONS"

OPERATIONS_FILE = os.environ.get(OPERATIONS_ENV_VAR)

current_api_only = pytest.mark.skipif(
    bool(OTHER_OPENAPI), reason="checks coverage of the current server's API, not an older one's"
)

BROWSER_ONLY_OPERATIONS: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/session"): (
        "exchanges a token for a session cookie; a bearer-token client doesn't need it, and aiohttp's default "
        "cookie jar drops the cookie from an IP-address host, so the call would succeed and store nothing"
    ),
}
"""Routes with no client method on purpose, each with the reason."""

PATH_KEYWORDS = frozenset({"instance"})
"""Keyword-only method parameters that go into the path rather than the query string."""

CALLS: dict[str, list[Callable[[HassetteClient], Awaitable[Any]]]] = {
    "get_health": [lambda c: c.get_health()],
    "get_liveness": [lambda c: c.get_liveness()],
    "get_ready": [lambda c: c.get_ready()],
    "get_apps": [lambda c: c.get_apps()],
    "get_app": [lambda c: c.get_app("my_app")],
    "action": [
        lambda c: c.action("my_app", "start"),
        lambda c: c.action("my_app", "stop"),
        lambda c: c.action("my_app", "reload"),
        lambda c: c.action("my_app", "start", instance=0),
        lambda c: c.action("my_app", "stop", instance=0),
        lambda c: c.action("my_app", "reload", instance=0),
    ],
    "get_app_config": [lambda c: c.get_app_config("my_app")],
    "get_app_source": [lambda c: c.get_app_source("my_app")],
    "get_recent_logs": [
        lambda c: c.get_recent_logs(
            limit=1, app_key="my_app", level="INFO", since=1.0, execution_id="exec-1", source_tier="all"
        )
    ],
    "set_log_level": [lambda c: c.set_log_level("hassette", "DEBUG")],
    "get_execution_logs": [lambda c: c.get_execution_logs("exec-1", limit=1)],
    "get_listeners": [
        lambda c: c.get_listeners(app_key="my_app", instance_index=0, since=1.0, source_tier="all"),
    ],
    "get_config": [lambda c: c.get_config()],
    "get_telemetry_status": [lambda c: c.get_telemetry_status()],
    "get_app_health": [lambda c: c.get_app_health("my_app", instance_index=0, since=1.0, source_tier="all")],
    "get_app_listeners": [lambda c: c.get_app_listeners("my_app", instance_index=0, since=1.0, source_tier="all")],
    "get_app_activity": [
        lambda c: c.get_app_activity("my_app", instance_index=0, limit=1, since=1.0, source_tier="all"),
    ],
    "get_app_jobs": [lambda c: c.get_app_jobs("my_app", instance_index=0, since=1.0, source_tier="all")],
    "get_app_blocking_findings": [lambda c: c.get_app_blocking_findings("my_app", instance_index=0, since=1.0)],
    "get_blocking_findings": [lambda c: c.get_blocking_findings(since=1.0)],
    "get_unattributed_blocking": [lambda c: c.get_unattributed_blocking(since=1.0)],
    "get_executions": [lambda c: c.get_executions(kind="job", limit=1, since=1.0)],
    "get_listener_executions": [lambda c: c.get_listener_executions(1, limit=1, since=1.0)],
    "get_job_executions": [lambda c: c.get_job_executions(1, limit=1, since=1.0)],
    "get_execution": [lambda c: c.get_execution("exec-1")],
    "get_app_grid": [lambda c: c.get_app_grid(since=1.0)],
    "get_jobs": [lambda c: c.get_jobs(since=1.0, source_tier="all")],
    "trigger_job": [lambda c: c.trigger_job(1)],
}
"""One call per route each public method serves, passing every keyword filter the method takes."""

STATUS_MODEL_503_METHODS = frozenset({"get_ready", "get_telemetry_status"})
"""The methods whose route answers a 503 with its status model rather than a problem body."""

PROBE_STATUS_BODY = {"status": "starting", "ready": False, "degraded": True}
"""A JSON 503 body both probe status models parse, so only a method's own 503 handling decides the outcome."""


def operations(spec_path: Path = OPENAPI_PATH) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, operation)
        for path, path_item in json.loads(spec_path.read_text())["paths"].items()
        for method, operation in path_item.items()
    ]


def template_pattern(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(path)) + "$")


def match_template(method: str, path: str, spec_path: Path = OPENAPI_PATH) -> tuple[str, str] | None:
    """Return the ``(method, template)`` of the operation a recorded request hit, or ``None`` if none does."""
    matches = [
        (m, template)
        for m, template, _ in operations(spec_path)
        if m == method and template_pattern(template).match(path)
    ]
    assert len(matches) <= 1, f"{method} {path} matches {matches}"
    return matches[0] if matches else None


def query_parameter_names(operation: dict[str, Any]) -> set[str]:
    return {parameter["name"] for parameter in operation.get("parameters", []) if parameter["in"] == "query"}


async def call_recording(
    client: HassetteClient, server: FakeServer, method_name: str
) -> list[tuple[str, str, frozenset[str]]]:
    """Run every call for ``method_name`` and return each request's method, path and query keys."""
    start = len(server.requests)
    for call in CALLS[method_name]:
        # The canned body won't parse as every model; only the request matters here.
        with contextlib.suppress(HassetteClientError):
            await call(client)
    return [(request.method, request.path, frozenset(request.query)) for request in server.requests[start:]]


async def all_requests(client: HassetteClient, server: FakeServer) -> dict[str, list[tuple[str, str, frozenset[str]]]]:
    server.respond(200, {})
    return {name: await call_recording(client, server, name) for name in CALLS}


def test_calls_cover_every_public_client_method() -> None:
    public = {
        name
        for name, member in inspect.getmembers(HassetteClient, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }

    assert public == set(CALLS)


async def test_every_keyword_filter_is_sent_under_its_own_name(client: HassetteClient, server: FakeServer) -> None:
    """Filters are named as the server names them, and ``CALLS`` passes each, so the spec check sees every one."""
    requests = await all_requests(client, server)
    unsent: dict[str, list[str]] = {}
    for method_name in CALLS:
        filters = {
            name
            for name, parameter in inspect.signature(getattr(HassetteClient, method_name)).parameters.items()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        } - PATH_KEYWORDS
        sent = {key for _, _, query in requests[method_name] for key in query}
        if filters - sent:
            unsent[method_name] = sorted(filters - sent)

    assert unsent == {}


async def test_every_client_request_exists_in_the_spec(client: HassetteClient, server: FakeServer) -> None:
    """Every route, method and query parameter the client sends is one the spec's server serves."""
    by_operation = {(method, path): operation for method, path, operation in operations()}
    missing_routes: list[str] = []
    unknown_parameters: list[str] = []
    for method_name, requests in (await all_requests(client, server)).items():
        for method, path, query in requests:
            operation = match_template(method, path)
            if operation is None:
                missing_routes.append(f"{method_name}: {method} {path}")
                continue
            declared = query_parameter_names(by_operation[operation])
            unknown_parameters.extend(f"{method_name}: {name} on {method} {path}" for name in sorted(query - declared))

    assert missing_routes == [], f"routes missing from {OPENAPI_PATH}"
    assert unknown_parameters == [], f"query parameters missing from {OPENAPI_PATH}"


@current_api_only
async def test_every_operation_has_a_client_method(client: HassetteClient, server: FakeServer) -> None:
    requested = {
        match_template(method, path)
        for requests in (await all_requests(client, server)).values()
        for method, path, _ in requests
    }
    expected = {(method, path) for method, path, _ in operations()}

    assert expected - requested - set(BROWSER_ONLY_OPERATIONS) == set(), "routes with no client method"
    assert set(BROWSER_ONLY_OPERATIONS) <= expected, "a browser-only exemption names a route that no longer exists"
    assert set(BROWSER_ONLY_OPERATIONS).isdisjoint(requested), "a browser-only route has a client method"


@current_api_only
async def test_every_declared_query_parameter_has_a_client_filter(client: HassetteClient, server: FakeServer) -> None:
    sent: dict[tuple[str, str], set[str]] = {}
    for requests in (await all_requests(client, server)).values():
        for method, path, query in requests:
            operation = match_template(method, path)
            assert operation is not None
            sent.setdefault(operation, set()).update(query)
    unexposed = {
        (method, path): sorted(query_parameter_names(operation) - sent.get((method, path), set()))
        for method, path, operation in operations()
        if (method, path) not in BROWSER_ONLY_OPERATIONS
    }

    assert {op: names for op, names in unexposed.items() if names} == {}


def expected_schema(annotation: Any) -> dict[str, Any]:
    """The OpenAPI schema FastAPI generates for a method's return annotation."""
    origin = get_origin(annotation)
    if origin is list:
        return {"type": "array", "items": expected_schema(get_args(annotation)[0])}
    if origin in (Union, types.UnionType):
        arms = [arg for arg in get_args(annotation) if arg is not type(None)]
        assert len(arms) == 1, annotation
        return {"anyOf": [expected_schema(arms[0]), {"type": "null"}]}
    return {"$ref": f"#/components/schemas/{annotation.__name__}"}


def without_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {key: without_titles(value) for key, value in schema.items() if key != "title"}
    if isinstance(schema, list):
        return [without_titles(item) for item in schema]
    return schema


@current_api_only
@pytest.mark.parametrize("method_name", sorted(CALLS))
async def test_every_method_return_type_matches_its_routes_response_schema(
    client: HassetteClient, server: FakeServer, method_name: str
) -> None:
    server.respond(200, {})
    by_operation = {(method, path): operation for method, path, operation in operations()}
    expected = expected_schema(get_type_hints(getattr(HassetteClient, method_name))["return"])

    for method, path, _ in await call_recording(client, server, method_name):
        operation = match_template(method, path)
        assert operation is not None
        successes = {
            status: response["content"]["application/json"]["schema"]
            for status, response in by_operation[operation]["responses"].items()
            if status.startswith("2")
        }
        assert len(successes) == 1, (operation, successes)
        assert without_titles(next(iter(successes.values()))) == expected, operation


@current_api_only
def test_every_declared_problem_code_resolves() -> None:
    """Each declared code is a known ``ProblemCode``, handled, and raises a subclass of its status's class."""
    for method, path, operation in operations():
        for status, response in operation["responses"].items():
            for code in response.get("x-problem-codes", []):
                problem_code = ProblemCode(code)
                assert problem_code in CODE_ERRORS or problem_code in GENERIC_CODES, (method, path, code)
                if problem_code in CODE_ERRORS:
                    family = error_class_for(int(status), None)
                    assert issubclass(CODE_ERRORS[problem_code], family), (method, path, status, code)


@pytest.mark.skipif(not OPERATIONS_FILE, reason=f"only when {OPERATIONS_ENV_VAR} names a file to write")
async def test_export_client_operations_for_floor_check(client: HassetteClient, server: FakeServer) -> None:
    """Not a check: the contract with ``tools/check_client_floor.py``, which filters oasdiff findings by it.

    Writes each operation the client calls, named as HEAD's spec names it (oasdiff's base), and whether the
    client parses that operation's 503 as a model.
    """
    assert OPERATIONS_FILE is not None
    parses_503_by_operation: dict[tuple[str, str], bool] = {}
    for method_name, requests in (await all_requests(client, server)).items():
        for method, path, _ in requests:
            key = match_template(method, path, HEAD_OPENAPI_PATH)
            assert key is not None, f"{method_name}: {method} {path} isn't in {HEAD_OPENAPI_PATH}"
            if method_name in STATUS_MODEL_503_METHODS:
                parses_503_by_operation[key] = True
            else:
                parses_503_by_operation.setdefault(key, False)

    Path(OPERATIONS_FILE).write_text(
        json.dumps(
            [
                {"method": method, "path": path, "parses_503": parses_503}
                for (method, path), parses_503 in sorted(parses_503_by_operation.items())
            ]
        )
    )


@pytest.mark.parametrize("method_name", sorted(CALLS))
async def test_only_status_model_methods_return_a_json_503(
    client: HassetteClient, server: FakeServer, method_name: str
) -> None:
    server.respond(503, PROBE_STATUS_BODY)
    returned = True
    for call in CALLS[method_name]:
        try:
            await call(client)
        except HassetteClientError:
            returned = False

    assert returned == (method_name in STATUS_MODEL_503_METHODS)


@current_api_only
@pytest.mark.parametrize("method_name", sorted(CALLS))
async def test_status_model_503_handling_matches_the_route(
    client: HassetteClient, server: FakeServer, method_name: str
) -> None:
    """A method returns its model on 503 exactly when the route documents a non-problem 503 body."""
    server.respond(200, {})
    by_operation = {(method, path): operation for method, path, operation in operations()}
    documents_status_model = False
    for method, path, _ in await call_recording(client, server, method_name):
        operation = match_template(method, path)
        assert operation is not None
        content = by_operation[operation]["responses"].get("503", {}).get("content", {})
        documents_status_model = documents_status_model or bool(set(content) - {PROBLEM_MEDIA_TYPE})

    assert documents_status_model == (method_name in STATUS_MODEL_503_METHODS)


@current_api_only
@pytest.mark.parametrize("method_name", sorted(CALLS))
async def test_no_route_documents_a_model_body_at_another_error_status(
    client: HassetteClient, server: FakeServer, method_name: str
) -> None:
    """Only a probe's 503 carries a model body among error statuses.

    ``tools/check_client_floor.py`` checks the floor release's responses only at 2xx and, for
    ``STATUS_MODEL_503_METHODS``, 503. A route that documents a model body at another error status needs
    that status added to the floor check's filter before this test may allow it.
    """
    server.respond(200, {})
    by_operation = {(method, path): operation for method, path, operation in operations()}
    unchecked: list[str] = []
    for method, path, _ in await call_recording(client, server, method_name):
        operation = match_template(method, path)
        assert operation is not None
        for status, response in by_operation[operation]["responses"].items():
            if status.startswith("2") or status == "503":
                continue
            if set(response.get("content", {})) - {PROBLEM_MEDIA_TYPE}:
                unchecked.append(f"{method} {path} {status}")

    assert unchecked == []

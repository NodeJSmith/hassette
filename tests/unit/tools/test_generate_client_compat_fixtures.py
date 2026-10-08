"""Tests for tools/generate_client_compat_fixtures.py: release-type encoding, route coverage, and real generation runs.

The generation tests seed the ``healthy`` scenario and serve it through HEAD's real FastAPI app, since what's
under test is that every route answers a body the fixture records faithfully. They type the fixtures with the
committed ``frontend/openapi.json`` (HEAD's spec) in place of a release's, so no release tags are needed.
"""

import json
from pathlib import Path

import pytest
from generate_client_compat_fixtures import (
    EXCLUDED_ROUTES,
    HEALTH_READY_UNAVAILABLE_REQUEST,
    PROBLEM_REQUESTS,
    PROBLEM_TYPE_SPEC,
    RELEASE_FILE,
    TELEMETRY_STATUS_UNAVAILABLE_REQUEST,
    TELEMETRY_UNAVAILABLE_REQUEST,
    FixtureRequest,
    Generated,
    SeedIds,
    check_response,
    generate,
    head_json_routes,
    release_response_types,
    schema_type_spec,
    success_requests,
    uncovered_routes,
    write_fixtures,
)
from hassette_wire import AppSummary, ProblemCode
from httpx2 import Response

from hassette.web.errors import PROBLEM_MEDIA_TYPE

HEAD_OPENAPI = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"

NO_IDS = SeedIds(app_key=None, listener_id=None, job_id=None, execution_id=None)


@pytest.fixture(scope="module")
def head_types() -> dict[tuple[str, str], object]:
    return release_response_types(json.loads(HEAD_OPENAPI.read_text()))


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ({"$ref": "#/components/schemas/AppSummary"}, "AppSummary"),
        ({"type": "array", "items": {"$ref": "#/components/schemas/LogEntry"}}, ["list", "LogEntry"]),
        (
            {"anyOf": [{"$ref": "#/components/schemas/Execution"}, {"type": "null"}]},
            ["union", "Execution", "None"],
        ),
    ],
)
def test_schema_type_spec(schema: dict[str, object], expected: object) -> None:
    assert schema_type_spec(schema) == expected


@pytest.mark.parametrize(
    "schema", [{"type": "object"}, {"$ref": "other.json#/Foo"}, {"type": "array"}, {"type": "string"}]
)
def test_schema_type_spec_rejects_unsupported_schemas(schema: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        schema_type_spec(schema)


def test_release_response_types_takes_each_routes_json_success_response(
    head_types: dict[tuple[str, str], object],
) -> None:
    assert head_types[("GET", "/api/apps/{app_key}")] == "AppSummary"
    assert head_types[("POST", "/api/apps/{app_key}/start")] == "ActionResponse"
    assert head_types[("GET", "/api/telemetry/execution/{execution_id}")] == ["union", "Execution", "None"]


def test_head_spec_types_every_covered_route(head_types: dict[tuple[str, str], object]) -> None:
    assert head_json_routes() - EXCLUDED_ROUTES.keys() <= head_types.keys()


def test_path_quotes_params() -> None:
    request = FixtureRequest("x", "GET", "/api/apps/{app_key}", {"app_key": "not a/key"})
    assert request.path == "/api/apps/not%20a%2Fkey"


def test_success_requests_skip_routes_missing_their_seed_id() -> None:
    with_ids = {r.route for r in success_requests(SeedIds("app", 1, 2, "exec"))}
    without_ids = {r.route for r in success_requests(NO_IDS)}

    assert "/api/telemetry/app/{app_key}/health" in with_ids - without_ids
    assert "/api/telemetry/execution/{execution_id}" in with_ids - without_ids
    assert "/api/health" in without_ids


def test_uncovered_routes_counts_only_success_requests() -> None:
    routes = [("GET", "/api/a"), ("GET", "/api/b"), ("GET", "/api/c"), *EXCLUDED_ROUTES]
    requests = [
        FixtureRequest("a", "GET", "/api/a"),
        FixtureRequest("b", "GET", "/api/b", problem_code=ProblemCode.NOT_FOUND),
        FixtureRequest("c", "GET", "/api/c", status_body_503=True),
    ]

    assert uncovered_routes(routes, requests) == ["GET /api/b", "GET /api/c"]


def test_a_request_cannot_be_both_a_problem_and_a_probe() -> None:
    with pytest.raises(ValueError, match="not both"):
        FixtureRequest("x", "GET", "/api/x", problem_code=ProblemCode.NOT_FOUND, status_body_503=True)


def problem_response(status: int, code: str) -> Response:
    return Response(status, json={"code": code}, headers={"content-type": PROBLEM_MEDIA_TYPE})


def test_check_response_rejects_a_problem_for_a_success_request() -> None:
    with pytest.raises(RuntimeError, match="expected a 2xx JSON body"):
        check_response("healthy", FixtureRequest("health", "GET", "/api/health"), problem_response(404, "not_found"))


@pytest.mark.parametrize(
    "response", [problem_response(400, "app_not_found"), problem_response(404, "instance_not_found")]
)
def test_check_response_rejects_the_wrong_problem(response: Response) -> None:
    request = FixtureRequest(
        "missing", "GET", "/api/apps/{app_key}", {"app_key": "x"}, problem_code=ProblemCode.APP_NOT_FOUND
    )
    with pytest.raises(RuntimeError, match="expected 404 'app_not_found'"):
        check_response("healthy", request, response)


def test_check_response_accepts_a_503_json_status_body_for_a_probe() -> None:
    response = Response(503, json={"ready": False}, headers={"content-type": "application/json"})

    check_response("healthy", HEALTH_READY_UNAVAILABLE_REQUEST, response)


@pytest.mark.parametrize(
    "response",
    [
        Response(200, json={"ready": True}, headers={"content-type": "application/json"}),
        problem_response(503, "telemetry_unavailable"),
        Response(503, json={"code": "telemetry_unavailable"}, headers={"content-type": "application/json"}),
    ],
)
def test_check_response_rejects_a_non_status_body_for_a_probe(response: Response) -> None:
    with pytest.raises(RuntimeError, match="expected a 503 application/json status body"):
        check_response("healthy", TELEMETRY_STATUS_UNAVAILABLE_REQUEST, response)


async def test_generate_types_every_response_by_the_release_spec(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    generated = await generate(["healthy"], head_types, tmp_path)

    assert generated.newer_than_release == []
    by_name = {fixture.request.name: fixture for fixture in generated.fixtures}
    for request in [*PROBLEM_REQUESTS, TELEMETRY_UNAVAILABLE_REQUEST]:
        assert by_name[request.name].response_type == PROBLEM_TYPE_SPEC
        assert json.loads(by_name[request.name].body)["code"] == request.problem_code
    healthy_counterpart = {
        HEALTH_READY_UNAVAILABLE_REQUEST.name: "health-ready",
        TELEMETRY_STATUS_UNAVAILABLE_REQUEST.name: "telemetry-status",
    }
    for name, healthy_name in healthy_counterpart.items():
        assert by_name[name].status == 503
        assert by_name[name].response_type == by_name[healthy_name].response_type
    app = by_name["app"]
    assert app.response_type == "AppSummary"
    assert AppSummary.model_validate_json(app.body).app_key == app.request.params["app_key"]


async def test_generate_writes_no_fixture_for_a_route_the_release_lacks(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    release_types = {key: spec for key, spec in head_types.items() if key != ("GET", "/api/telemetry/app-grid")}

    generated = await generate(["healthy"], release_types, tmp_path)

    assert generated.newer_than_release == ["GET /api/telemetry/app-grid"]
    assert "app-grid" not in {fixture.request.name for fixture in generated.fixtures}


async def test_write_fixtures_names_the_release(tmp_path: Path, head_types: dict[tuple[str, str], object]) -> None:
    generated = await generate(["healthy"], head_types, tmp_path)
    output = tmp_path / "fixtures"

    write_fixtures(output, generated, "v1.2.3")

    assert json.loads((output / RELEASE_FILE).read_text()) == {"tag": "v1.2.3", "version": "1.2.3"}
    fixture = json.loads((output / "healthy--app.json").read_text())
    assert fixture["route"] == "GET /api/apps/{app_key}"
    assert fixture["request"].startswith("GET /api/apps/")
    assert len(list(output.glob("healthy--*.json"))) == len(generated.fixtures)


async def test_generate_fails_when_a_release_route_has_no_request(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    release_types = {**head_types, ("GET", "/api/apps/{key}/renamed"): "AppSummary"}

    with pytest.raises(RuntimeError, match=r"GET /api/apps/\{key\}/renamed"):
        await generate(["healthy"], release_types, tmp_path)


def test_write_fixtures_normalizes_a_pre_release_version(tmp_path: Path) -> None:
    write_fixtures(tmp_path, Generated([], []), "v1.0.0-rc1")

    assert json.loads((tmp_path / RELEASE_FILE).read_text())["version"] == "1.0.0rc1"

"""Tests for tools/generate_client_compat_fixtures.py: release-type encoding, response checks, and real generation runs.

The generation tests seed the ``healthy`` scenario and serve it through HEAD's real FastAPI app, since what's
under test is that every route answers a body the fixture records faithfully. They type the fixtures with the
committed ``frontend/openapi.json`` (HEAD's spec) in place of a release's, so no release tags are needed.
"""

import json
from pathlib import Path

import pytest
from client_compat_coverage import EXCLUDED
from client_compat_requests import (
    HEALTH_READY_UNAVAILABLE_REQUEST,
    PROBLEM_REQUESTS,
    TELEMETRY_STATUS_UNAVAILABLE_REQUEST,
    TELEMETRY_UNAVAILABLE_REQUEST,
    FixtureRequest,
)
from fastapi import FastAPI
from generate_client_compat_fixtures import (
    PROBLEM_TYPE_SPEC,
    RELEASE_FILE,
    STUB_VARIANTS,
    Fixture,
    Generated,
    check_response,
    generate,
    head_json_routes,
    print_notice,
    release_response_types,
    schema_type_spec,
    summary_lines,
    write_fixtures,
)
from hassette_wire import AppStatus, AppSummary, ProblemCode, ResourceStatus
from httpx2 import Response

from hassette.web.app import create_fastapi_app
from hassette.web.errors import PROBLEM_MEDIA_TYPE
from tests.support.web_mocks import create_hassette_stub

HEAD_OPENAPI = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


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
    head_routes = head_json_routes(create_fastapi_app(create_hassette_stub()))
    excluded = {target for kind, target in EXCLUDED if kind == "route"}
    assert {(method, path) for method, path in head_routes if f"{method} {path}" not in excluded} <= head_types.keys()


def test_head_json_routes_rejects_an_api_route_without_a_response_model() -> None:
    app = FastAPI()

    @app.get("/api/untyped", response_model=None)
    async def untyped() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    with pytest.raises(RuntimeError, match="GET /api/untyped"):
        head_json_routes(app)


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
    variant_requests = [request for variant in STUB_VARIANTS for request in variant.requests]
    for request in [*PROBLEM_REQUESTS, *variant_requests, TELEMETRY_UNAVAILABLE_REQUEST]:
        if request.problem_code is None:
            continue
        assert by_name[request.name].response_type == PROBLEM_TYPE_SPEC
        assert by_name[request.name].content_type == PROBLEM_MEDIA_TYPE
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


async def test_generate_reports_every_live_app_status(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    generated = await generate(["healthy"], head_types, tmp_path)

    by_name = {fixture.request.name: fixture for fixture in generated.fixtures}
    apps = json.loads(by_name["apps"].body)["apps"]
    assert {app["status"] for app in apps} == set(AppStatus)
    assert {instance["status"] for app in apps for instance in app["instances"]} == set(ResourceStatus)
    assert len(json.loads(by_name["execution-logs"].body)["records"]) == 2
    assert json.loads(by_name["execution-failed"].body)["error_traceback"]
    degraded_rows = json.loads(by_name["app-grid-degraded"].body)["apps"]
    assert degraded_rows
    assert all(row["activity"]["activity_buckets"] is None for row in degraded_rows)
    assert {code.value for code in ProblemCode} - {fixture.request.problem_code for fixture in generated.fixtures} == {
        target for kind, target in EXCLUDED if kind == "problem"
    }


async def test_generate_writes_no_fixture_for_a_route_the_release_lacks(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    release_types = {key: spec for key, spec in head_types.items() if key != ("GET", "/api/telemetry/app-grid")}

    generated = await generate(["healthy"], release_types, tmp_path)

    assert generated.newer_than_release == ["GET /api/telemetry/app-grid"]
    assert not {"app-grid", "app-grid-degraded"} & {fixture.request.name for fixture in generated.fixtures}


async def test_generate_fails_when_a_release_route_has_no_request(
    tmp_path: Path, head_types: dict[tuple[str, str], object]
) -> None:
    release_types = {**head_types, ("GET", "/api/apps/{key}/renamed"): "AppSummary"}

    with pytest.raises(RuntimeError, match=r"route GET /api/apps/\{key\}/renamed"):
        await generate(["healthy"], release_types, tmp_path)


def test_write_fixtures_lists_the_release_fixtures_and_skipped_routes(tmp_path: Path) -> None:
    fixtures = [
        Fixture("healthy", FixtureRequest(name, "GET", "/api/health"), 200, "application/json", "HealthResponse", "{}")
        for name in ("b", "a")
    ]
    generated = Generated(fixtures, ["GET /api/new"], [])

    write_fixtures(tmp_path, generated, "v1.2.3")

    assert json.loads((tmp_path / RELEASE_FILE).read_text()) == {
        "tag": "v1.2.3",
        "version": "1.2.3",
        "fixtures": ["healthy--a.json", "healthy--b.json"],
        "newer_than_release": ["GET /api/new"],
    }
    written = json.loads((tmp_path / "healthy--a.json").read_text())
    assert written["route"] == "GET /api/health"
    assert (written["content_type"], written["probe"], written["problem_code"]) == ("application/json", False, None)
    assert sorted(path.name for path in tmp_path.glob("healthy--*.json")) == ["healthy--a.json", "healthy--b.json"]


def test_write_fixtures_normalizes_a_pre_release_version(tmp_path: Path) -> None:
    write_fixtures(tmp_path, Generated([], [], []), "v1.0.0-rc1")

    assert json.loads((tmp_path / RELEASE_FILE).read_text())["version"] == "1.0.0rc1"


def test_summary_lines_add_the_skipped_routes_to_the_coverage_summary() -> None:
    summary = summary_lines(Generated([], ["GET /api/new"], ["routes: 30 of 31 covered, 1 excluded"]), "v1.2.3")

    assert summary == [
        "routes: 30 of 31 covered, 1 excluded",
        "routes newer than v1.2.3, skipped: 1 (GET /api/new)",
    ]


@pytest.mark.parametrize(("actions", "prefix"), [("true", "::warning title=client-compat release::"), ("", "")])
def test_print_notice_annotates_under_github_actions(
    actions: str, prefix: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", actions)

    print_notice("v1.2.0 skipped")

    assert capsys.readouterr().out == f"{prefix}v1.2.0 skipped\n"

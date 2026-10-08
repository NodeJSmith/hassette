"""CI: write golden response fixtures from HEAD's web API, for ``tools/check_client_compat.py``.

Each seed scenario (``scripts/seed_db.py``) is served by HEAD's real FastAPI app over a stub
``Hassette``: telemetry comes from the seeded database through a real ``TelemetryQueryService``, and
live state (apps, scheduler, config) from the e2e mock fixtures. Every JSON route is requested at
least once, plus a set of problem requests, each checked for its ``ProblemCode``.

Each fixture records the response body and the type the *latest release* declares for that route in
its ``openapi.json``. hassette-client's tests require each method to parse its route's declared
schema, so that is the type the released client parses; taking it from HEAD instead would hide a
route whose model was swapped or renamed. A route the release doesn't have gets no fixture, since
the released client never calls it. ``release.json`` next to the fixtures names the release, so the
checker installs that exact client version.

The fixtures are generated in CI rather than committed, so they can't drift from the scenarios. Run
through ``uv run nox -s client_compat``. Rationale:
``design/research/2026-10-02-hassette-client-transport/research.md``, "Q5. Cross-version CI".
"""

import argparse
import asyncio
import json
import sqlite3
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The seed scenarios live in scripts/ and the e2e mock fixtures in tests/; neither is installed.
for import_root in (REPO_ROOT, SCRIPTS_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import aiosqlite  # noqa: E402
from check_wire_compat import extract_tagged_openapi, resolve_latest_release_tag  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from hassette_wire import ProblemCode  # noqa: E402
from httpx2 import ASGITransport, AsyncClient, Response  # noqa: E402
from packaging.version import Version  # noqa: E402
from seed_db import generate_scenario  # noqa: E402
from seed_scenarios import SCENARIOS  # noqa: E402

from hassette.core.telemetry.query_service import TelemetryQueryService  # noqa: E402
from hassette.web.app import create_fastapi_app  # noqa: E402
from hassette.web.errors import CODE_STATUS, PROBLEM_MEDIA_TYPE  # noqa: E402
from tests.e2e.mock_fixtures import (  # noqa: E402
    APP_KEY_MY_APP,
    MANUAL_JOB_ID,
    build_manifests,
    build_scheduler_jobs,
    wire_app_manifest_lookups,
    wire_config,
    wire_scheduler_trigger,
)
from tests.support.web_mocks import create_hassette_stub, create_mock_runtime_query_service  # noqa: E402

DEFAULT_SCENARIOS = tuple(name for name in SCENARIOS if name != "large-volume")
"""``large-volume`` adds bulk, not new shapes, and would multiply the fixture size."""

EXCLUDED_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/session"): "browser-only: hassette-client has no method for it",
}
"""Routes with no fixture on purpose, each with the reason."""

RELEASE_FILE = "release.json"
"""Names the release the fixtures' types come from; read by the nox session and the checker."""

READ_TIMEOUT_SECONDS = 5.0

UNKNOWN_EXECUTION_UUID = "00000000-0000-4000-8000-000000000000"
"""``/api/executions/{execution_id}`` requires a UUID, and no seed scenario's execution IDs are UUIDs, so
this request gets the empty result."""

TypeSpec = str | list["TypeSpec"]
"""A JSON-safe response type: a ``hassette_wire`` export name, ``"None"``, ``["list", item]`` or
``["union", *members]``. ``tools/check_client_compat.py`` rebuilds it against the released wire."""

PROBLEM_TYPE_SPEC: TypeSpec = "ProblemDetail"

SCHEMA_REF_PREFIX = "#/components/schemas/"

ALL_TIERS = {"source_tier": "all"}
"""Routes that filter by source tier default to ``app``; ``all`` puts framework rows in the fixtures too."""


@dataclass(frozen=True)
class FixtureRequest:
    """One request whose response becomes a fixture."""

    name: str
    method: str
    route: str
    """The route's path template. The ``not_found`` request uses a path no route serves."""
    params: Mapping[str, str | int] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] | None = None
    problem_code: ProblemCode | None = None
    """The code a problem request must answer with; ``None`` for a success request."""

    @property
    def path(self) -> str:
        return self.route.format(**{key: quote(str(value), safe="") for key, value in self.params.items()})


@dataclass(frozen=True)
class SeedIds:
    """Identifiers present in one seeded database, ``None`` where the scenario has none."""

    app_key: str | None
    listener_id: int | None
    job_id: int | None
    execution_id: str | None


@dataclass(frozen=True)
class Fixture:
    scenario: str
    request: FixtureRequest
    status: int
    response_type: TypeSpec
    body: str

    @property
    def file_name(self) -> str:
        return f"{self.scenario}--{self.request.name}.json"

    def to_json(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "name": self.request.name,
            "route": f"{self.request.method} {self.request.route}",
            "request": f"{self.request.method} {self.request.path}",
            "status": self.status,
            "response_type": self.response_type,
            "body": self.body,
        }


@dataclass(frozen=True)
class Generated:
    fixtures: list[Fixture]
    newer_than_release: list[str]
    """Routes HEAD serves that the release doesn't, so no fixture was written for them."""


PROBLEM_REQUESTS = [
    FixtureRequest(
        "problem-invalid-app-key",
        "GET",
        "/api/apps/{app_key}",
        {"app_key": "not a key"},
        problem_code=ProblemCode.INVALID_APP_KEY,
    ),
    FixtureRequest(
        "problem-app-not-found",
        "GET",
        "/api/apps/{app_key}",
        {"app_key": "no_such_app"},
        problem_code=ProblemCode.APP_NOT_FOUND,
    ),
    FixtureRequest(
        "problem-instance-not-found",
        "POST",
        "/api/apps/{app_key}/instances/{index}/start",
        {"app_key": APP_KEY_MY_APP, "index": 99},
        problem_code=ProblemCode.INSTANCE_NOT_FOUND,
    ),
    FixtureRequest(
        "problem-validation-failed",
        "GET",
        "/api/telemetry/executions",
        query={"limit": "not-a-number"},
        problem_code=ProblemCode.VALIDATION_FAILED,
    ),
    FixtureRequest("problem-not-found", "GET", "/api/no-such-route", problem_code=ProblemCode.NOT_FOUND),
    FixtureRequest("problem-method-not-allowed", "DELETE", "/api/apps", problem_code=ProblemCode.METHOD_NOT_ALLOWED),
]
"""Problem bodies don't depend on the seeded data, so they're requested against one scenario only."""

TELEMETRY_UNAVAILABLE_REQUEST = FixtureRequest(
    "problem-telemetry-unavailable",
    "GET",
    "/api/telemetry/executions",
    problem_code=ProblemCode.TELEMETRY_UNAVAILABLE,
)
"""Sent after the database connection is closed, which is what makes telemetry unavailable."""


def success_requests(ids: SeedIds) -> list[FixtureRequest]:
    """One request per JSON route, skipping routes that need an identifier ``ids`` lacks.

    Telemetry routes take identifiers from the seeded database. App actions, app config and
    source, and the job trigger read the stub's live state, so they use the e2e fixtures' keys.
    """
    my_app = {"app_key": APP_KEY_MY_APP}
    my_app_instance = {"app_key": APP_KEY_MY_APP, "index": 0}
    requests = [
        FixtureRequest("health", "GET", "/api/health"),
        FixtureRequest("health-live", "GET", "/api/health/live"),
        FixtureRequest("health-ready", "GET", "/api/health/ready"),
        FixtureRequest("apps", "GET", "/api/apps"),
        FixtureRequest("app-start", "POST", "/api/apps/{app_key}/start", my_app),
        FixtureRequest("app-stop", "POST", "/api/apps/{app_key}/stop", my_app),
        FixtureRequest("app-reload", "POST", "/api/apps/{app_key}/reload", my_app),
        FixtureRequest("app-instance-start", "POST", "/api/apps/{app_key}/instances/{index}/start", my_app_instance),
        FixtureRequest("app-instance-stop", "POST", "/api/apps/{app_key}/instances/{index}/stop", my_app_instance),
        FixtureRequest("app-instance-reload", "POST", "/api/apps/{app_key}/instances/{index}/reload", my_app_instance),
        FixtureRequest("app-config", "GET", "/api/apps/{app_key}/config", my_app),
        FixtureRequest("app-source", "GET", "/api/apps/{app_key}/source", my_app),
        FixtureRequest("logs-recent", "GET", "/api/logs/recent", query=ALL_TIERS),
        FixtureRequest("log-level", "PUT", "/api/logs/level", body={"logger": "hassette", "level": "DEBUG"}),
        FixtureRequest(
            "execution-logs", "GET", "/api/executions/{execution_id}", {"execution_id": UNKNOWN_EXECUTION_UUID}
        ),
        FixtureRequest("bus-listeners", "GET", "/api/bus/listeners", query=ALL_TIERS),
        FixtureRequest("config", "GET", "/api/config"),
        FixtureRequest("telemetry-status", "GET", "/api/telemetry/status"),
        FixtureRequest("blocking-findings", "GET", "/api/telemetry/blocking/findings"),
        FixtureRequest("blocking-unattributed", "GET", "/api/telemetry/blocking/unattributed"),
        FixtureRequest("executions", "GET", "/api/telemetry/executions"),
        FixtureRequest("app-grid", "GET", "/api/telemetry/app-grid"),
        FixtureRequest("scheduler-jobs", "GET", "/api/scheduler/jobs", query=ALL_TIERS),
        FixtureRequest("job-trigger", "POST", "/api/scheduler/jobs/{job_id}/trigger", {"job_id": MANUAL_JOB_ID}),
    ]
    if ids.app_key is not None:
        app = {"app_key": ids.app_key}
        requests += [
            FixtureRequest("app", "GET", "/api/apps/{app_key}", app),
            FixtureRequest("app-health", "GET", "/api/telemetry/app/{app_key}/health", app, ALL_TIERS),
            FixtureRequest("app-listeners", "GET", "/api/telemetry/app/{app_key}/listeners", app, ALL_TIERS),
            FixtureRequest("app-activity", "GET", "/api/telemetry/app/{app_key}/activity", app, ALL_TIERS),
            FixtureRequest("app-jobs", "GET", "/api/telemetry/app/{app_key}/jobs", app, ALL_TIERS),
            FixtureRequest("app-blocking", "GET", "/api/telemetry/app/{app_key}/blocking", app),
        ]
    if ids.listener_id is not None:
        listener = {"listener_id": ids.listener_id}
        requests.append(
            FixtureRequest("listener-executions", "GET", "/api/telemetry/listener/{listener_id}/executions", listener)
        )
    if ids.job_id is not None:
        requests.append(
            FixtureRequest("job-executions", "GET", "/api/telemetry/job/{job_id}/executions", {"job_id": ids.job_id})
        )
    if ids.execution_id is not None:
        execution = {"execution_id": ids.execution_id}
        requests.append(FixtureRequest("execution", "GET", "/api/telemetry/execution/{execution_id}", execution))
    return requests


def schema_type_spec(schema: Mapping[str, Any]) -> TypeSpec:
    """Encode an OpenAPI response schema as the type the released client parses it with.

    Raises:
        ValueError: The schema is something other than a component reference, ``null``, an array
            or an ``anyOf`` of those.
    """
    if ref := schema.get("$ref"):
        if not ref.startswith(SCHEMA_REF_PREFIX):
            raise ValueError(f"unsupported $ref {ref!r}")
        return ref.removeprefix(SCHEMA_REF_PREFIX)
    if schema.get("type") == "null":
        return "None"
    if schema.get("type") == "array" and "items" in schema:
        return ["list", schema_type_spec(schema["items"])]
    if members := schema.get("anyOf"):
        return ["union", *(schema_type_spec(member) for member in members)]
    raise ValueError(f"unsupported response schema {schema!r}")


def release_response_types(openapi: Mapping[str, Any]) -> dict[tuple[str, str], TypeSpec]:
    """Each (method, path template) in ``openapi`` mapped to its JSON success response's type."""
    response_types: dict[tuple[str, str], TypeSpec] = {}
    for path, operations in openapi["paths"].items():
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                if status.startswith("2") and schema is not None:
                    response_types[(method.upper(), path)] = schema_type_spec(schema)
                    break
    return response_types


def head_json_routes() -> set[tuple[str, str]]:
    """Every (method, path template) HEAD serves with a response model."""
    app = create_fastapi_app(create_hassette_stub())
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.response_model is not None
        for method in route.methods
    }


def uncovered_routes(routes: Iterable[tuple[str, str]], requests: Iterable[FixtureRequest]) -> list[str]:
    """The routes no success request reaches and :data:`EXCLUDED_ROUTES` doesn't name."""
    accounted = {(r.method, r.route) for r in requests if r.problem_code is None} | EXCLUDED_ROUTES.keys()
    return sorted(f"{method} {path}" for method, path in routes if (method, path) not in accounted)


def read_seed_ids(db_path: Path) -> SeedIds:
    conn = sqlite3.connect(db_path)
    try:
        return SeedIds(
            app_key=first_value(conn, "SELECT app_key FROM listeners ORDER BY id LIMIT 1")
            or first_value(conn, "SELECT app_key FROM app_manifests ORDER BY app_key LIMIT 1"),
            listener_id=first_value(conn, "SELECT id FROM listeners ORDER BY id LIMIT 1"),
            job_id=first_value(conn, "SELECT id FROM scheduled_jobs ORDER BY id LIMIT 1"),
            execution_id=first_value(conn, "SELECT execution_id FROM executions ORDER BY id LIMIT 1"),
        )
    finally:
        conn.close()


def first_value(conn: sqlite3.Connection, query: str) -> Any:
    row = conn.execute(query).fetchone()
    return row[0] if row else None


def build_app(read_db: aiosqlite.Connection) -> Any:
    """HEAD's FastAPI app over a stub ``Hassette`` whose telemetry reads ``read_db``.

    The live-state wiring follows ``build_mock_hassette`` in ``tests/e2e/conftest.py``, minus its mocked
    telemetry; compare against it when a route starts failing here.
    """
    manifests = build_manifests()
    hassette = create_hassette_stub(manifests=manifests, scheduler_jobs=build_scheduler_jobs(), app_action_mocks=True)
    create_mock_runtime_query_service(hassette)
    wire_app_manifest_lookups(hassette, manifests)
    wire_config(hassette)
    wire_scheduler_trigger(hassette, {MANUAL_JOB_ID: "send_notification"})
    hassette.database_service.read_db = read_db
    hassette.config.database.read_timeout_seconds = READ_TIMEOUT_SECONDS
    hassette.telemetry_query_service = TelemetryQueryService(hassette)
    return create_fastapi_app(hassette)


def check_response(scenario: str, request: FixtureRequest, response: Response) -> None:
    """Raise if ``response`` isn't what ``request`` expects.

    Raises:
        RuntimeError: A success request didn't answer 2xx JSON, or a problem request didn't answer
            its code's status with a problem body carrying that code. The generator, not the
            released client, is broken.
    """
    where = f"{scenario}: {request.method} {request.path} answered {response.status_code}"
    content_type = response.headers.get("content-type", "")
    if request.problem_code is None:
        if not response.is_success or not content_type.startswith("application/json"):
            raise RuntimeError(f"{where} ({content_type}), expected a 2xx JSON body: {response.text[:500]}")
        return
    expected_status = CODE_STATUS[request.problem_code]
    code = response.json().get("code") if content_type.startswith(PROBLEM_MEDIA_TYPE) else None
    if response.status_code != expected_status or code != request.problem_code:
        raise RuntimeError(
            f"{where} ({content_type}, code {code!r}), expected {expected_status} {request.problem_code.value!r}"
        )


async def serve_scenario(
    db_path: Path, requests: Iterable[FixtureRequest], *, with_problems: bool
) -> list[tuple[FixtureRequest, Response]]:
    """Send ``requests`` (and the problem requests, if ``with_problems``) to an app over ``db_path``."""
    read_db = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    read_db.row_factory = aiosqlite.Row
    async with AsyncClient(transport=ASGITransport(app=build_app(read_db)), base_url="http://hassette") as client:
        try:
            exchanges = [
                (request, await client.request(request.method, request.path, params=request.query, json=request.body))
                for request in [*requests, *(PROBLEM_REQUESTS if with_problems else [])]
            ]
        finally:
            await read_db.close()
        if with_problems:
            unavailable = TELEMETRY_UNAVAILABLE_REQUEST
            exchanges.append((unavailable, await client.request(unavailable.method, unavailable.path)))
    return exchanges


async def generate(
    scenarios: Iterable[str], release_types: Mapping[tuple[str, str], TypeSpec], work_dir: Path
) -> Generated:
    """Seed and serve each scenario, and pair each response with the type the release declares for it.

    The problem requests go to the first scenario only.

    Raises:
        RuntimeError: A response isn't what its request expects, or a JSON route HEAD or the release
            serves has no success request in any scenario and isn't in :data:`EXCLUDED_ROUTES`. Covering
            the release's routes too means a route HEAD renamed or removed fails here, rather than
            silently losing its fixture.
    """
    fixtures: list[Fixture] = []
    newer_than_release: set[str] = set()
    sent: list[FixtureRequest] = []
    for index, scenario in enumerate(scenarios):
        db_path = work_dir / f"{scenario}.db"
        generate_scenario(scenario, output_path=db_path, tmp_path=work_dir / f"{scenario}.db.tmp")
        requests = success_requests(read_seed_ids(db_path))
        sent += requests
        for request, response in await serve_scenario(db_path, requests, with_problems=index == 0):
            check_response(scenario, request, response)
            if request.problem_code is not None:
                response_type = PROBLEM_TYPE_SPEC
            elif (response_type := release_types.get((request.method, request.route))) is None:
                newer_than_release.add(f"{request.method} {request.route}")
                continue
            fixtures.append(Fixture(scenario, request, response.status_code, response_type, response.text))
    uncovered = uncovered_routes(head_json_routes() | release_types.keys(), sent)
    if uncovered:
        raise RuntimeError(
            "No fixture request covers these routes HEAD or the release serves; add one to success_requests() "
            "or, with the reason, to EXCLUDED_ROUTES:\n  " + "\n  ".join(uncovered)
        )
    return Generated(fixtures, sorted(newer_than_release))


def write_fixtures(output: Path, generated: Generated, release_tag: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for fixture in generated.fixtures:
        (output / fixture.file_name).write_text(json.dumps(fixture.to_json(), indent=2) + "\n")
    # Normalized, so a pre-release tag (v1.0.0-rc1) matches the version the installed package reports (1.0.0rc1).
    release = {"tag": release_tag, "version": str(Version(release_tag.removeprefix("v")))}
    (output / RELEASE_FILE).write_text(json.dumps(release, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write HEAD web API response fixtures.")
    parser.add_argument("--output", type=Path, required=True, help="Directory to write the fixture files to.")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SCENARIOS),
        help=f"Seed scenario to serve; repeatable (default: {', '.join(DEFAULT_SCENARIOS)}).",
    )
    args = parser.parse_args(argv)
    scenarios = args.scenario or list(DEFAULT_SCENARIOS)

    tag = resolve_latest_release_tag(REPO_ROOT)
    if tag is None:
        print("No 'v*' release tag reachable from HEAD; fetch tags (fetch-depth: 0).", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as work_dir:
        release_types = release_response_types(
            json.loads(extract_tagged_openapi(REPO_ROOT, tag, Path(work_dir)).read_text())
        )
        generated = asyncio.run(generate(scenarios, release_types, Path(work_dir)))
    write_fixtures(args.output, generated, tag)

    for route in generated.newer_than_release:
        print(f"no fixture for {route}: {tag} doesn't serve it")
    print(
        f"Wrote {len(generated.fixtures)} fixtures from {len(scenarios)} scenario(s) to {args.output}, typed by {tag}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""CI: write golden response fixtures from HEAD's web API, for ``tools/check_client_compat.py``.

Each seed scenario (``scripts/seed_db.py``) is served by HEAD's real FastAPI app over a stub
``Hassette``: telemetry comes from the seeded database through a real ``TelemetryQueryService``, and
live state (apps, scheduler, config) from the e2e mock fixtures. ``tools/client_compat_live_state.py``
adds what neither has (more app states, a logged failed execution, blocking stacks). The requests are in
``tools/client_compat_requests.py``; what they must cover is in ``tools/client_compat_coverage.py``, and
generation fails on any gap.

The release is the newest hassette-client PyPI serves whose ``v*`` tag is reachable from HEAD (see
``tools/client_compat_release.py``). Each fixture records the response, its content type, and the type
that release declares for that route in its ``openapi.json``. hassette-client's tests require each method
to parse its route's declared schema, so that is the type the released client parses; taking it from HEAD
instead would hide a route whose model was swapped or renamed. A route the release doesn't have gets no
fixture, since the released client never calls it. ``release.json`` next to the fixtures names the
release, so the checker installs that exact client version, and lists the fixtures and skipped routes.

The fixtures are generated in CI rather than committed, so they can't drift from the scenarios. Run
through ``uv run nox -s client_compat``.

Rationale: the approach (server-generated fixtures run through the release's own ``interpret_response``) is
in ``design/research/2026-10-08-released-client-compat-approaches/research.md``, and the release selection in
``design/research/2026-10-08-client-compat-release-baseline/research.md``. The check originates in
``design/research/2026-10-02-hassette-client-transport/research.md``, "Q5. Cross-version CI".

The ``sys.path`` setup below adds ``scripts/`` and the repo root (``tools/``, this file's directory, is
already first when it runs as a script), so sibling tool modules, the seed scenarios and ``tests`` import as
top-level names.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The seed scenarios live in scripts/ and the e2e mock fixtures in tests/; neither is installed.
for import_root in (REPO_ROOT, SCRIPTS_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import aiosqlite  # noqa: E402
import httpx2  # noqa: E402
from check_wire_compat import extract_tagged_openapi, list_release_tags  # noqa: E402
from client_compat_coverage import EXCLUDED, Answered, coverage_report  # noqa: E402
from client_compat_live_state import (  # noqa: E402
    break_runtime_overlay,
    fail_activity_buckets,
    hold_bootstrap,
    live_manifests,
    read_seed_ids,
    seed_live_state,
    wire_app_outcomes,
)
from client_compat_release import PYPI_CLIENT_URL, choose_release, published_client_versions  # noqa: E402
from client_compat_requests import (  # noqa: E402
    APP_GRID_DEGRADED_REQUEST,
    AUTH_TOKEN,
    BOOTSTRAP_NOT_RELEASED_REQUEST,
    HEALTH_READY_UNAVAILABLE_REQUEST,
    INTERNAL_ERROR_REQUEST,
    PROBLEM_REQUESTS,
    TELEMETRY_STATUS_UNAVAILABLE_REQUEST,
    TELEMETRY_UNAVAILABLE_REQUEST,
    FixtureRequest,
    success_requests,
)
from fastapi import FastAPI  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from httpx2 import ASGITransport, AsyncClient, Response  # noqa: E402
from packaging.version import Version  # noqa: E402
from seed_db import generate_scenario  # noqa: E402
from seed_scenarios import SCENARIOS  # noqa: E402

from hassette.core.telemetry.query_service import TelemetryQueryService  # noqa: E402
from hassette.web.app import API_PREFIX, create_fastapi_app  # noqa: E402
from hassette.web.errors import CODE_STATUS, PROBLEM_MEDIA_TYPE  # noqa: E402
from tests.e2e.mock_fixtures import (  # noqa: E402
    MANUAL_JOB_ID,
    build_scheduler_jobs,
    wire_app_manifest_lookups,
    wire_config,
    wire_scheduler_trigger,
)
from tests.support.web_mocks import create_hassette_stub, create_mock_runtime_query_service  # noqa: E402

DEFAULT_SCENARIOS = tuple(name for name in SCENARIOS if name != "large-volume")
"""``large-volume`` adds bulk, not new shapes, and would multiply the fixture size."""

# Kept in sync with RELEASE_FILE in tools/check_client_compat.py and the literal in noxfile.py's client_compat.
RELEASE_FILE = "release.json"
"""Names the release the fixtures' types come from, and lists the fixtures; read by the nox session and the checker."""

RELEASE_NOTICE_PREFIX = "::warning title=client-compat release::"
"""GitHub Actions workflow-command syntax: printed under Actions, a line with this prefix shows on the run."""

STEP_SUMMARY_ENV = "GITHUB_STEP_SUMMARY"

READ_TIMEOUT_SECONDS = 5.0

BASE_URL = "http://hassette"

TypeSpec = str | list["TypeSpec"]
"""A JSON-safe response type: a ``hassette_wire`` export name, ``"None"``, ``["list", item]`` or
``["union", *members]``. :func:`schema_type_spec` writes it and ``resolve_type`` in
``tools/check_client_compat.py`` rebuilds it against the released wire; the two are kept in sync."""

PROBLEM_TYPE_SPEC: TypeSpec = "ProblemDetail"

SCHEMA_REF_PREFIX = "#/components/schemas/"

StubTweak = Callable[[MagicMock], None]

Exchange = tuple[FixtureRequest, Response]
"""A request paired with the response HEAD's app answered it with."""


@dataclass(frozen=True)
class Fixture:
    scenario: str
    request: FixtureRequest
    status: int
    content_type: str
    response_type: TypeSpec
    body: str

    @property
    def file_name(self) -> str:
        return f"{self.scenario}--{self.request.name}.json"

    def to_json(self) -> dict[str, Any]:
        problem_code = self.request.problem_code
        return {
            "scenario": self.scenario,
            "name": self.request.name,
            "route": self.request.route_key,
            "request": f"{self.request.method} {self.request.path}",
            "status": self.status,
            "content_type": self.content_type,
            "probe": self.request.probe,
            "problem_code": problem_code.value if problem_code is not None else None,
            "response_type": self.response_type,
            "body": self.body,
        }


@dataclass(frozen=True)
class Generated:
    fixtures: list[Fixture]
    newer_than_release: list[str]
    """Routes HEAD serves that the release doesn't, so no fixture was written for them."""
    coverage_summary: list[str]
    """What the fixtures cover, one line per coverage kind (``tools/client_compat_coverage.py``)."""


@dataclass(frozen=True)
class StubVariant:
    """Requests sent to their own app, built with one stub tweak the shared app can't carry."""

    tweak: StubTweak
    requests: tuple[FixtureRequest, ...]
    raise_app_exceptions: bool = True
    """``False`` where the request reaches the 500 handler, which re-raises after answering."""


STUB_VARIANTS = (
    StubVariant(hold_bootstrap, (HEALTH_READY_UNAVAILABLE_REQUEST, BOOTSTRAP_NOT_RELEASED_REQUEST)),
    StubVariant(fail_activity_buckets, (APP_GRID_DEGRADED_REQUEST,)),
    StubVariant(break_runtime_overlay, (INTERNAL_ERROR_REQUEST,), raise_app_exceptions=False),
)
"""Sent to the first scenario only, over its still-open database (see :func:`serve_failure_paths`)."""


def schema_type_spec(schema: Mapping[str, Any]) -> TypeSpec:
    """Encode an OpenAPI response schema as the type the released client parses it with.

    The decoding half is ``resolve_type`` in ``tools/check_client_compat.py``; a shape added here needs a case
    there.

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


def head_json_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path template) ``app`` serves under ``/api/``, after checking each one is typed.

    It's a guard as well as a getter: it raises rather than return a route whose body has no declared type
    for the released client's parsing to be checked against.

    Raises:
        RuntimeError: An ``/api/`` route has no response model and no ``route`` entry in :data:`EXCLUDED`,
            so its body has no declared type to check.
    """
    routes = {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(f"{API_PREFIX}/")
        for method in route.methods
    }
    untyped = sorted(
        f"{method} {path}"
        for (method, path), route in routes.items()
        if route.response_model is None and ("route", f"{method} {path}") not in EXCLUDED
    )
    if untyped:
        raise RuntimeError(
            "These routes have no response_model, so the released client's parsing of them can't be "
            "checked; declare one, or exclude the route in EXCLUDED with the reason:\n  " + "\n  ".join(untyped)
        )
    return set(routes)


def build_app(read_db: aiosqlite.Connection, tweak: StubTweak | None = None) -> FastAPI:
    """HEAD's FastAPI app over a stub ``Hassette`` whose telemetry reads ``read_db``.

    ``tweak``, when given, changes the stub once it's wired (see :data:`STUB_VARIANTS`).

    The live-state wiring follows ``build_mock_hassette`` in ``tests/e2e/conftest.py``, minus its mocked
    telemetry; compare against it when a route starts failing here.
    """
    manifests = live_manifests()
    hassette = create_hassette_stub(manifests=manifests, scheduler_jobs=build_scheduler_jobs(), app_action_mocks=True)
    create_mock_runtime_query_service(hassette)
    wire_app_manifest_lookups(hassette, manifests)
    wire_app_outcomes(hassette, manifests)
    # Replaces the stub's whole config, so auth is switched on here rather than on the stub.
    wire_config(hassette, auth_enabled=True)
    wire_scheduler_trigger(hassette, {MANUAL_JOB_ID: "send_notification"})
    hassette.database_service.read_db = read_db
    hassette.config.database.read_timeout_seconds = READ_TIMEOUT_SECONDS
    hassette.telemetry_query_service = TelemetryQueryService(hassette)
    if tweak is not None:
        tweak(hassette)
    return create_fastapi_app(hassette, auth_token=AUTH_TOKEN)


def check_response(scenario: str, request: FixtureRequest, response: Response) -> None:
    """Raise if ``response`` isn't what ``request`` expects.

    Raises:
        RuntimeError: A success request didn't answer 2xx JSON, a probe request didn't answer 503
            with a plain JSON status body, or a problem request didn't answer its code's
            status with a problem body carrying that code. The generator, not the released client,
            is broken.
    """
    where = f"{scenario}: {request.method} {request.path} answered {response.status_code}"
    content_type = response.headers.get("content-type", "")
    if request.probe:
        # A status model has no ``code``; a problem body always does.
        if (
            response.status_code != 503
            or not content_type.startswith("application/json")
            or not isinstance(body := response.json(), dict)
            or "code" in body
        ):
            raise RuntimeError(
                f"{where} ({content_type}), expected a 503 application/json status body: {response.text[:500]}"
            )
        return
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


async def send(client: AsyncClient, request: FixtureRequest) -> Exchange:
    """Send ``request`` and pair it with its response."""
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"} if request.authenticated else {}
    response = await client.request(
        request.method, request.path, params=request.query, json=request.body, headers=headers
    )
    return request, response


async def send_all(client: AsyncClient, requests: Iterable[FixtureRequest]) -> list[Exchange]:
    """Send ``requests`` in order, pairing each with its response."""
    return [await send(client, request) for request in requests]


async def serve_scenario(
    db_path: Path, requests: Iterable[FixtureRequest], *, with_failure_paths: bool
) -> list[Exchange]:
    """Send ``requests`` to an app over ``db_path``, plus the failure-path requests if ``with_failure_paths``."""
    read_db = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        read_db.row_factory = aiosqlite.Row
        async with AsyncClient(transport=ASGITransport(app=build_app(read_db)), base_url=BASE_URL) as client:
            exchanges = await send_all(client, requests)
            if with_failure_paths:
                exchanges += await serve_failure_paths(client, read_db)
    finally:
        # Covers every exit. After the failure paths have closed read_db this second close is harmless:
        # aiosqlite's close() returns at once on a closed connection.
        await read_db.close()
    return exchanges


async def serve_failure_paths(client: AsyncClient, read_db: aiosqlite.Connection) -> list[Exchange]:
    """Send the failure-path requests, in the only order that works.

    The problem requests and the stub variants need ``read_db`` open; the telemetry-unavailable requests need
    it closed, so closing it is the last phase.
    """
    exchanges = await send_all(client, PROBLEM_REQUESTS)
    exchanges += await serve_stub_variants(read_db)
    exchanges += await serve_with_telemetry_closed(client, read_db)
    return exchanges


async def serve_stub_variants(read_db: aiosqlite.Connection) -> list[Exchange]:
    """Send each :data:`STUB_VARIANTS` entry's requests to its own app over the still-open ``read_db``."""
    exchanges: list[Exchange] = []
    for variant in STUB_VARIANTS:
        app = build_app(read_db, variant.tweak)
        transport = ASGITransport(app=app, raise_app_exceptions=variant.raise_app_exceptions)
        async with AsyncClient(transport=transport, base_url=BASE_URL) as variant_client:
            exchanges += await send_all(variant_client, variant.requests)
    return exchanges


async def serve_with_telemetry_closed(client: AsyncClient, read_db: aiosqlite.Connection) -> list[Exchange]:
    """Close ``read_db``, which is what makes telemetry unavailable, then send the requests that need that."""
    await read_db.close()
    return await send_all(client, (TELEMETRY_UNAVAILABLE_REQUEST, TELEMETRY_STATUS_UNAVAILABLE_REQUEST))


def type_for(request: FixtureRequest, release_types: Mapping[tuple[str, str], TypeSpec]) -> TypeSpec | None:
    """The type the release parses ``request``'s response as, or ``None`` when the release lacks the route.

    A problem response is a ``ProblemDetail`` whatever the route.
    """
    if request.problem_code is not None:
        return PROBLEM_TYPE_SPEC
    return release_types.get((request.method, request.route))


async def generate(
    scenarios: Iterable[str], release_types: Mapping[tuple[str, str], TypeSpec], work_dir: Path
) -> Generated:
    """Seed and serve each scenario, and pair each response with the type the release declares for it.

    The problem, stub-variant and probe requests go to the first scenario only.

    Raises:
        RuntimeError: A response isn't what its request expects, or the responses leave a coverage gap
            (``tools/client_compat_coverage.py``). Covering the release's routes too means a route HEAD
            renamed or removed fails here, rather than silently losing its fixture.
    """
    fixtures: list[Fixture] = []
    newer_than_release: set[str] = set()
    answered: list[Answered] = []
    manifests = live_manifests()
    for index, scenario in enumerate(scenarios):
        db_path = work_dir / f"{scenario}.db"
        generate_scenario(scenario, output_path=db_path, tmp_path=work_dir / f"{scenario}.db.tmp")
        seed_live_state(db_path, manifests)
        requests = success_requests(read_seed_ids(db_path))
        for request, response in await serve_scenario(db_path, requests, with_failure_paths=index == 0):
            check_response(scenario, request, response)
            answered.append((request, response.json()))
            response_type = type_for(request, release_types)
            if response_type is None:
                newer_than_release.add(request.route_key)
                continue
            content_type = response.headers.get("content-type", "")
            fixtures.append(
                Fixture(scenario, request, response.status_code, content_type, response_type, response.text)
            )
    routes = head_json_routes(create_fastapi_app(create_hassette_stub())) | release_types.keys()
    coverage = coverage_report(routes, answered)
    if coverage.gaps:
        raise RuntimeError(
            "The fixtures leave these gaps; close each one, or exclude it in EXCLUDED "
            "(tools/client_compat_coverage.py) with the reason:\n  " + "\n  ".join(coverage.gaps)
        )
    return Generated(fixtures, sorted(newer_than_release), coverage.summary)


def write_fixtures(output: Path, generated: Generated, release_tag: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for fixture in generated.fixtures:
        (output / fixture.file_name).write_text(json.dumps(fixture.to_json(), indent=2) + "\n")
    release = {
        "tag": release_tag,
        # Normalized, so the tag's spelling (v1.0.0-rc1) matches the version the installed package reports (1.0.0rc1).
        "version": str(Version(release_tag.removeprefix("v"))),
        "fixtures": sorted(fixture.file_name for fixture in generated.fixtures),
        "newer_than_release": generated.newer_than_release,
    }
    (output / RELEASE_FILE).write_text(json.dumps(release, indent=2) + "\n")


def summary_lines(generated: Generated, release_tag: str) -> list[str]:
    """The coverage summary, plus the routes skipped because ``release_tag`` doesn't have them."""
    newer = generated.newer_than_release
    skipped = f"routes newer than {release_tag}, skipped: {len(newer)}" + (f" ({', '.join(newer)})" if newer else "")
    return [*generated.coverage_summary, skipped]


def print_notice(message: str) -> None:
    """Print ``message``, as a workflow warning annotation under GitHub Actions so it shows on the run."""
    prefix = RELEASE_NOTICE_PREFIX if os.environ.get("GITHUB_ACTIONS") == "true" else ""
    print(f"{prefix}{message}")


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

    reachable_tags = list_release_tags(REPO_ROOT)
    if not reachable_tags:
        print("No 'v*' release tag reachable from HEAD; fetch tags (fetch-depth: 0).", file=sys.stderr)
        return 1
    try:
        published = published_client_versions()
    except httpx2.HTTPError as exc:
        print(f"Couldn't list hassette-client releases on PyPI ({PYPI_CLIENT_URL}): {exc}", file=sys.stderr)
        return 1
    tag, notices = choose_release(reachable_tags, published)
    for notice in notices:
        print_notice(notice)
    if tag is None:
        print(f"None of the {len(reachable_tags)} release tags reachable from HEAD is on PyPI.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as work_dir:
        release_types = release_response_types(
            json.loads(extract_tagged_openapi(REPO_ROOT, tag, Path(work_dir)).read_text())
        )
        generated = asyncio.run(generate(scenarios, release_types, Path(work_dir)))
    write_fixtures(args.output, generated, tag)

    summary = summary_lines(generated, tag)
    print(
        f"Wrote {len(generated.fixtures)} fixtures from {len(scenarios)} scenario(s) to {args.output}, typed by {tag}."
    )
    for line in summary:
        print(f"  {line}")
    if step_summary := os.environ.get(STEP_SUMMARY_ENV):
        with Path(step_summary).open("a") as file:
            file.write(f"### Client compat coverage ({len(generated.fixtures)} fixtures, typed by {tag})\n\n")
            file.writelines(f"- {line}\n" for line in summary)
            file.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

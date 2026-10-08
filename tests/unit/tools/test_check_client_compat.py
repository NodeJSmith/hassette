"""Tests for tools/check_client_compat.py, run against the workspace hassette-client.

The tool's job in CI is to run in a venv holding the released client; here the workspace copy stands in
for it, ``repo_root`` points elsewhere so the "imported from this checkout" guard stays quiet, and the
fixtures' ``release.json`` names the workspace version.
"""

import json
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import check_client_compat
import pytest
from check_client_compat import (
    RELEASE_FILE,
    REPO_ROOT,
    MissingTypeError,
    check_fixture,
    main,
    resolve_type,
    setup_problem,
)
from generate_client_compat_fixtures import generate, release_response_types, schema_type_spec, write_fixtures
from hassette_wire import AppSummary, Execution, LogEntry

from tests.unit.tools.test_generate_client_compat_fixtures import HEAD_OPENAPI

JSON = "application/json"
PROBLEM = "application/problem+json"


def problem_body(status: int, code: str) -> str:
    return json.dumps({"type": "about:blank", "title": "Error", "status": status, "detail": "detail", "code": code})


def write_fixture(
    directory: Path,
    name: str,
    response_type: object,
    body: str,
    *,
    status: int = 200,
    content_type: str = JSON,
    probe: bool = False,
    problem_code: str | None = None,
) -> Path:
    path = directory / f"{name}.json"
    fixture = {
        "route": "GET /api/example",
        "request": "GET /api/example",
        "status": status,
        "content_type": content_type,
        "probe": probe,
        "problem_code": problem_code,
        "response_type": response_type,
        "body": body,
    }
    path.write_text(json.dumps(fixture))
    return path


def write_release(directory: Path, client_version: str, *, newer_than_release: list[str] | None = None) -> None:
    """Write ``release.json`` listing the fixtures already in ``directory``."""
    fixtures = sorted(path.name for path in directory.glob("*.json") if path.name != RELEASE_FILE)
    release = {
        "tag": f"v{client_version}",
        "version": client_version,
        "fixtures": fixtures,
        "newer_than_release": newer_than_release or [],
    }
    (directory / RELEASE_FILE).write_text(json.dumps(release))


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("AppSummary", AppSummary),
        ("None", type(None)),
        (["list", "LogEntry"], list[LogEntry]),
        (["union", "Execution", "None"], Execution | None),
    ],
)
def test_resolve_type(spec: object, expected: object) -> None:
    assert resolve_type(spec) == expected


def test_resolve_type_round_trips_every_head_route_schema() -> None:
    openapi = json.loads(HEAD_OPENAPI.read_text())
    for spec in release_response_types(openapi).values():
        resolve_type(spec)
    assert resolve_type(schema_type_spec({"$ref": "#/components/schemas/AppSummary"})) is AppSummary


def test_resolve_type_reports_a_model_the_release_lacks() -> None:
    with pytest.raises(MissingTypeError, match="NoSuchModel"):
        resolve_type(["list", "NoSuchModel"])


@pytest.mark.parametrize("spec", [["dict", "AppSummary"], ["union"], 3])
def test_resolve_type_rejects_unknown_specs(spec: object) -> None:
    with pytest.raises(ValueError, match="unrecognized response type spec"):
        resolve_type(spec)


def test_check_fixture_fails_a_body_that_does_not_parse(tmp_path: Path) -> None:
    failure = check_fixture(write_fixture(tmp_path, "bad", ["list", "LogEntry"], '[{"id": "not-a-number"}]'))

    assert failure is not None
    assert failure.route == "GET /api/example"
    assert "GET /api/example" in failure.reason


def test_check_fixture_fails_a_type_the_release_lacks(tmp_path: Path) -> None:
    failure = check_fixture(write_fixture(tmp_path, "renamed", "NoSuchModel", "{}"))

    assert failure is not None
    assert "has no NoSuchModel" in failure.reason


def test_check_fixture_reports_an_unrecognized_type_spec_instead_of_raising(tmp_path: Path) -> None:
    failure = check_fixture(write_fixture(tmp_path, "odd", ["dict", "AppSummary"], "{}"))

    assert failure is not None
    assert failure.route == "GET /api/example"
    assert "ValueError" in failure.reason


def test_check_fixture_fails_a_success_body_sent_as_a_problem(tmp_path: Path) -> None:
    failure = check_fixture(write_fixture(tmp_path, "mislabeled", "None", "null", content_type=PROBLEM))

    assert failure is not None
    assert "non-JSON body (application/problem+json" in failure.reason


@pytest.mark.parametrize(("status", "code"), [(409, "app_blocked"), (404, "not_found"), (500, "internal_error")])
def test_check_fixture_passes_a_problem_the_release_raises_as_its_code(tmp_path: Path, status: int, code: str) -> None:
    path = write_fixture(
        tmp_path,
        "problem",
        "ProblemDetail",
        problem_body(status, code),
        status=status,
        content_type=PROBLEM,
        problem_code=code,
    )

    assert check_fixture(path) is None


def test_check_fixture_fails_a_problem_whose_code_the_release_maps_differently(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path,
        "problem",
        "ProblemDetail",
        problem_body(500, "action_failed"),
        status=500,
        content_type=PROBLEM,
        problem_code="app_blocked",
    )

    failure = check_fixture(path)

    assert failure is not None
    assert "ActionFailedError with code 'action_failed', expected code 'app_blocked'" in failure.reason


def test_check_fixture_fails_a_problem_the_release_does_not_raise(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, "parsed", "None", "null", status=200, content_type=JSON, problem_code="not_found")

    failure = check_fixture(path)

    assert failure is not None
    assert "instead of raising" in failure.reason


def test_check_fixture_passes_a_probe_status_body(tmp_path: Path) -> None:
    body = json.dumps({"status": "degraded", "ready": False})
    path = write_fixture(tmp_path, "probe", "ReadinessResponse", body, status=503, probe=True)

    assert check_fixture(path) is None


def test_main_refuses_the_workspace_client(tmp_path: Path) -> None:
    write_fixture(tmp_path, "ok", "None", "null")
    write_release(tmp_path, version("hassette-client"))

    assert main([str(tmp_path)], repo_root=REPO_ROOT) == 1


def test_main_refuses_a_different_client_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_fixture(tmp_path, "ok", "None", "null")
    write_release(tmp_path, "0.0.1")

    assert main([str(tmp_path)], repo_root=tmp_path / "elsewhere") == 1
    assert "typed by hassette-client 0.0.1" in capsys.readouterr().err


def test_main_fails_without_fixtures(tmp_path: Path) -> None:
    write_release(tmp_path, version("hassette-client"))

    assert main([str(tmp_path)], repo_root=tmp_path / "elsewhere") == 1


def test_setup_problem_names_a_missing_release_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_release(tmp_path, version("hassette-client"))
    monkeypatch.setattr(check_client_compat, "missing_release_symbol", "cannot import name 'RawResponse'")

    problem = setup_problem(tmp_path, tmp_path / "elsewhere")

    assert problem is not None
    assert "RawResponse" in problem
    assert "update tools/check_client_compat.py" in problem


def test_setup_problem_names_a_changed_interpret_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interpret_response(response: object, response_type: object, endpoint: str) -> None: ...

    write_release(tmp_path, version("hassette-client"))
    monkeypatch.setattr(check_client_compat, "interpret_response", interpret_response)

    problem = setup_problem(tmp_path, tmp_path / "elsewhere")

    assert problem is not None
    assert "interpret_response has no status_model_on_503 parameter" in problem
    assert "update tools/check_client_compat.py" in problem


def test_setup_problem_names_a_raw_response_field_the_release_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @dataclass(frozen=True)
    class RawResponse:
        status: int
        media_type: str | None
        kind: object
        body: bytes
        truncated: bool
        location: str | None

    write_release(tmp_path, version("hassette-client"))
    monkeypatch.setattr(check_client_compat, "RawResponse", RawResponse)

    problem = setup_problem(tmp_path, tmp_path / "elsewhere")

    assert problem is not None
    assert "RawResponse has no payload field" in problem


def test_setup_problem_names_fixtures_missing_from_disk(tmp_path: Path) -> None:
    write_fixture(tmp_path, "kept", "None", "null")
    write_fixture(tmp_path, "lost", "None", "null")
    write_release(tmp_path, version("hassette-client"))
    (tmp_path / "lost.json").unlink()

    problem = setup_problem(tmp_path, tmp_path / "elsewhere")

    assert problem is not None
    assert "missing ['lost.json'], unlisted []" in problem


def test_setup_problem_names_fixtures_the_release_does_not_list(tmp_path: Path) -> None:
    write_release(tmp_path, version("hassette-client"))
    write_fixture(tmp_path, "stray", "None", "null")

    problem = setup_problem(tmp_path, tmp_path / "elsewhere")

    assert problem is not None
    assert "missing [], unlisted ['stray.json']" in problem


def test_main_prints_the_routes_newer_than_the_release(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_fixture(tmp_path, "ok", "None", "null")
    write_release(tmp_path, version("hassette-client"), newer_than_release=["GET /api/new"])

    assert main([str(tmp_path)], repo_root=tmp_path / "elsewhere") == 0
    assert "doesn't call GET /api/new" in capsys.readouterr().out


async def test_main_passes_generated_fixtures_and_names_a_broken_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = tmp_path / "fixtures"
    generated = await generate(["healthy"], release_response_types(json.loads(HEAD_OPENAPI.read_text())), tmp_path)
    write_fixtures(fixtures, generated, f"v{version('hassette-client')}")
    elsewhere = tmp_path / "elsewhere"

    assert main([str(fixtures)], repo_root=elsewhere) == 0

    broken = fixtures / "healthy--executions.json"
    fixture = json.loads(broken.read_text())
    rows = json.loads(fixture["body"])
    rows[0]["execution_start_ts"] = "2026-01-15T12:00:00+00:00"
    broken.write_text(json.dumps({**fixture, "body": json.dumps(rows)}))

    assert main([str(fixtures)], repo_root=elsewhere) == 1
    err = capsys.readouterr().err
    assert "GET /api/telemetry/executions (healthy--executions.json)" in err
    assert "execution_start_ts" in err

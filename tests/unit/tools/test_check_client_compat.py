"""Tests for tools/check_client_compat.py, run against the workspace hassette-client.

The tool's job in CI is to run in a venv holding the released client; here the workspace copy stands in
for it, ``repo_root`` points elsewhere so the "imported from this checkout" guard stays quiet, and the
fixtures' ``release.json`` names the workspace version.
"""

import json
from importlib.metadata import version
from pathlib import Path

import pytest
from check_client_compat import RELEASE_FILE, REPO_ROOT, MissingTypeError, check_fixture, main, resolve_type
from generate_client_compat_fixtures import generate, release_response_types, schema_type_spec, write_fixtures
from hassette_wire import AppSummary, Execution, LogEntry

from tests.unit.tools.test_generate_client_compat_fixtures import HEAD_OPENAPI


def write_fixture(directory: Path, name: str, response_type: object, body: str) -> Path:
    path = directory / f"{name}.json"
    fixture = {
        "route": "GET /api/example",
        "request": "GET /api/example",
        "status": 200,
        "response_type": response_type,
        "body": body,
    }
    path.write_text(json.dumps(fixture))
    return path


def write_release(directory: Path, client_version: str) -> None:
    (directory / RELEASE_FILE).write_text(json.dumps({"tag": f"v{client_version}", "version": client_version}))


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


def test_main_refuses_the_workspace_client(tmp_path: Path) -> None:
    write_release(tmp_path, version("hassette-client"))
    write_fixture(tmp_path, "ok", "None", "null")

    assert main([str(tmp_path)], repo_root=REPO_ROOT) == 1


def test_main_refuses_a_different_client_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_release(tmp_path, "0.0.1")
    write_fixture(tmp_path, "ok", "None", "null")

    assert main([str(tmp_path)], repo_root=tmp_path / "elsewhere") == 1
    assert "typed by hassette-client 0.0.1" in capsys.readouterr().err


def test_main_fails_without_fixtures(tmp_path: Path) -> None:
    write_release(tmp_path, version("hassette-client"))

    assert main([str(tmp_path)], repo_root=tmp_path / "elsewhere") == 1


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

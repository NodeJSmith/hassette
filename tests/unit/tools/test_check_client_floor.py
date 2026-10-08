"""Tests for tools/check_client_floor.py: which release is the floor, and which oasdiff findings block.

Real git plumbing, since tag lookup and ``git show`` are the thing under test. The finding filter runs
the real ``oasdiff`` binary, since the shape of its findings (status only in ``text``) is what the filter
depends on; those tests skip when ``oasdiff`` isn't on PATH, like ``test_check_wire_compat.py``.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import check_client_floor
import pytest
from check_client_floor import (
    SCHEMA_MODULE_RELATIVE_PATH,
    history_problem,
    main,
    resolve_floor,
    run_request_check,
    schema_version_at,
    schema_version_in,
    select_client_findings,
)
from check_wire_compat import OPENAPI_RELATIVE_PATH, REPO_ROOT, run_oasdiff

from tests.unit.tools.conftest import GitRepo

FIXTURES = Path(__file__).parent / "fixtures" / "client_floor"

needs_oasdiff = pytest.mark.skipif(shutil.which("oasdiff") is None, reason="oasdiff not found on PATH")

CALLS_THING_ONLY = [{"method": "GET", "path": "/api/thing", "parses_503": False}]
"""An operations file where the client calls only ``GET /api/thing`` and doesn't parse its 503 as a model."""


def write_spec(repo: GitRepo, marker: str) -> None:
    repo.write(OPENAPI_RELATIVE_PATH, json.dumps({"openapi": "3.1.0", "info": {"title": marker}}))


def write_schema(repo: GitRepo, version: int) -> None:
    repo.write(SCHEMA_MODULE_RELATIVE_PATH, f'"""Health models."""\n\nAPI_SCHEMA_VERSION = {version}\n')


def release(repo: GitRepo, tag: str, marker: str, schema: int | None) -> None:
    write_spec(repo, marker)
    if schema is not None:
        write_schema(repo, schema)
    repo.commit(marker)
    subprocess.run(["git", "tag", tag], cwd=repo.root, check=True, capture_output=True)


def spec_title(path: Path) -> str:
    return json.loads(path.read_text())["info"]["title"]


def operation_spec(responses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A one-operation spec, ``GET /api/thing``, answering each status with an object of the given schema."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "client-floor-fixture", "version": "1"},
        "paths": {
            "/api/thing": {
                "get": {
                    "operationId": "getThing",
                    "responses": {
                        status: {"description": "r", "content": {"application/json": {"schema": schema}}}
                        for status, schema in responses.items()
                    },
                }
            }
        },
    }


def object_with_ab(required: list[str]) -> dict[str, Any]:
    """An object schema with string properties ``a`` and ``b``; ``required`` names which of them are required."""
    return {"type": "object", "required": required, "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}


def reversed_findings(tmp_path: Path, head: dict[str, Any], floor: dict[str, Any]) -> list[dict[str, Any]]:
    head_path, floor_path = tmp_path / "head.json", tmp_path / "floor.json"
    head_path.write_text(json.dumps(head))
    floor_path.write_text(json.dumps(floor))
    return run_oasdiff(head_path, floor_path, None, "test")


def test_schema_version_in_reads_an_annotated_constant() -> None:
    assert schema_version_in("API_SCHEMA_VERSION: int = 4\n") == 4


def test_schema_version_in_refuses_a_value_it_cant_read() -> None:
    """Reading ``BASE + 1`` as 0 would silently move the floor."""
    with pytest.raises(RuntimeError, match="int literal"):
        schema_version_in("BASE = 1\nAPI_SCHEMA_VERSION = BASE + 1\n")


def test_schema_version_in_reads_the_module_constant() -> None:
    assert schema_version_in("API_SCHEMA_VERSION = 3\n") == 3
    assert schema_version_in("OTHER = 3\n") == 0


def test_tag_without_the_schema_file_counts_as_zero(git_repo: GitRepo) -> None:
    release(git_repo, "v1.0.0", "old", schema=None)

    assert schema_version_at(git_repo.root, "v1.0.0") == 0


def test_floor_is_the_oldest_tag_at_or_above_the_minimum(git_repo: GitRepo, tmp_path: Path) -> None:
    release(git_repo, "v1.0.0", "pre-schema", schema=None)
    release(git_repo, "v1.1.0", "schema-1", schema=1)
    release(git_repo, "v1.2.0", "schema-2", schema=2)
    release(git_repo, "v1.3.0", "still-2", schema=2)
    dest = tmp_path / "out"
    dest.mkdir()

    assert spec_title(resolve_floor(git_repo.root, 2, dest).spec) == "schema-2"
    assert spec_title(resolve_floor(git_repo.root, 1, dest).spec) == "schema-1"


def test_no_qualifying_tag_falls_back_to_heads_spec(
    git_repo: GitRepo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release(git_repo, "v1.0.0", "pre-schema", schema=None)
    write_spec(git_repo, "head")
    write_schema(git_repo, 1)
    git_repo.commit("introduce the schema")

    floor = resolve_floor(git_repo.root, 1, tmp_path)

    assert floor.tag is None
    assert floor.spec == git_repo.root / OPENAPI_RELATIVE_PATH
    assert "Floor release: HEAD (no release reports API schema 1 yet)" in capsys.readouterr().out


@pytest.mark.parametrize("rc_schema", [None, 1], ids=["tagged-before-the-bump", "carrying-the-schema"])
def test_walk_reaching_a_pre_release_tag_fails(git_repo: GitRepo, tmp_path: Path, rc_schema: int | None) -> None:
    """Git's version sort puts v1.1.0rc1 above v1.1.0; until that's ordered (KI-001), the walk must not pass."""
    release(git_repo, "v1.0.0", "pre-schema", schema=None)
    release(git_repo, "v1.1.0", "schema-1", schema=1)
    release(git_repo, "v1.1.0rc1", "rc", schema=rc_schema)

    with pytest.raises(RuntimeError, match=r"reached v1\.1\.0rc1, which isn't a final"):
        resolve_floor(git_repo.root, 1, tmp_path)


def test_history_problem_refuses_a_tagless_checkout(git_repo: GitRepo) -> None:
    write_schema(git_repo, 1)
    git_repo.commit("no tags")

    assert (
        history_problem(git_repo.root) == "No v* release tags are reachable from HEAD; fetch tags (git fetch --tags)."
    )


def test_history_problem_refuses_a_shallow_checkout(git_repo: GitRepo, tmp_path: Path) -> None:
    release(git_repo, "v1.0.0", "first", schema=1)
    write_spec(git_repo, "second")
    git_repo.commit("second")
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{git_repo.root}", str(clone)], check=True, capture_output=True
    )

    problem = history_problem(clone)

    assert problem is not None
    assert "shallow" in problem


def test_history_problem_accepts_full_history_with_tags(git_repo: GitRepo) -> None:
    release(git_repo, "v1.0.0", "first", schema=1)

    assert history_problem(git_repo.root) is None


def test_unknown_tag_raises_rather_than_reading_as_zero(git_repo: GitRepo) -> None:
    release(git_repo, "v1.0.0", "first", schema=1)

    with pytest.raises(RuntimeError, match=r"git ls-tree v9\.9\.9 failed"):
        schema_version_at(git_repo.root, "v9.9.9")


def test_minimum_above_heads_schema_fails_before_running_anything(
    git_repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    write_schema(git_repo, 1)
    git_repo.commit("server at schema 1")

    assert main(git_repo.root, min_schema=2) == 1
    err = capsys.readouterr().err
    assert "above the API_SCHEMA_VERSION this checkout serves (1)" in err
    assert "MIN_API_SCHEMA_VERSION docstring" in err


@needs_oasdiff
def test_v0_55_0_apps_list_break_blocks_and_its_422_findings_dont() -> None:
    """The verified break: a v0.55.0 server's ``GET /api/apps`` lacks fields this client requires."""
    findings = run_oasdiff(REPO_ROOT / OPENAPI_RELATIVE_PATH, FIXTURES / "v0.55.0-openapi.json", None, "test")
    operations = [
        {"method": "GET", "path": "/api/apps", "parses_503": False},
        {"method": "GET", "path": "/api/apps/{app_key}/config", "parses_503": False},
    ]

    blocking = select_client_findings(findings, operations)

    assert any(f["path"] == "/api/apps" and "`200` status" in f["text"] for f in blocking)
    assert not any("`422`" in f["text"] for f in blocking)
    # Nothing on an operation the client doesn't call.
    assert {(f["operation"], f["path"]) for f in blocking} <= {(op["method"], op["path"]) for op in operations}


@needs_oasdiff
def test_success_field_that_became_optional_blocks(tmp_path: Path) -> None:
    findings = reversed_findings(
        tmp_path, operation_spec({"200": object_with_ab(["a", "b"])}), operation_spec({"200": object_with_ab(["a"])})
    )

    assert [f["id"] for f in select_client_findings(findings, CALLS_THING_ONLY)] == [
        "response-property-became-optional"
    ]


@needs_oasdiff
def test_problem_status_findings_dont_block(tmp_path: Path) -> None:
    findings = reversed_findings(
        tmp_path,
        operation_spec({"200": object_with_ab(["a"]), "422": object_with_ab(["a", "b"])}),
        operation_spec({"200": object_with_ab(["a"]), "422": object_with_ab(["a"])}),
    )

    assert findings
    assert select_client_findings(findings, CALLS_THING_ONLY) == []


@needs_oasdiff
def test_503_blocks_only_for_a_probe_method(tmp_path: Path) -> None:
    findings = reversed_findings(
        tmp_path,
        operation_spec({"200": object_with_ab(["a"]), "503": object_with_ab(["a", "b"])}),
        operation_spec({"200": object_with_ab(["a"]), "503": object_with_ab(["a"])}),
    )
    probe = [{"method": "GET", "path": "/api/thing", "parses_503": True}]

    assert select_client_findings(findings, CALLS_THING_ONLY) == []
    assert len(select_client_findings(findings, probe)) == 1


@needs_oasdiff
def test_operation_the_client_doesnt_call_doesnt_block(tmp_path: Path) -> None:
    findings = reversed_findings(
        tmp_path, operation_spec({"200": object_with_ab(["a", "b"])}), operation_spec({"200": object_with_ab(["a"])})
    )

    assert select_client_findings(findings, [{"method": "GET", "path": "/api/other", "parses_503": False}]) == []


@needs_oasdiff
@pytest.mark.parametrize(
    ("floor_a_schema", "finding_id"),
    [
        ({"type": "integer"}, "response-property-type-changed"),
        ({"type": "string", "nullable": True}, "response-property-became-nullable"),
    ],
)
def test_floor_field_the_client_cant_parse_blocks(
    tmp_path: Path, floor_a_schema: dict[str, Any], finding_id: str
) -> None:
    head = operation_spec({"200": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}})
    floor = operation_spec({"200": {"type": "object", "required": ["a"], "properties": {"a": floor_a_schema}}})

    findings = reversed_findings(tmp_path, head, floor)

    assert [f["id"] for f in select_client_findings(findings, CALLS_THING_ONLY)] == [finding_id]


@needs_oasdiff
def test_floor_without_the_success_response_blocks(tmp_path: Path) -> None:
    findings = reversed_findings(
        tmp_path, operation_spec({"200": object_with_ab(["a"])}), operation_spec({"201": object_with_ab(["a"])})
    )

    assert [f["id"] for f in select_client_findings(findings, CALLS_THING_ONLY)] == ["response-success-status-removed"]


@needs_oasdiff
def test_coverage_export_feeds_the_response_filter(tmp_path: Path) -> None:
    """End to end: the coverage test's export, as the tool runs it, feeds the filter with oasdiff's own paths."""
    operations_file = tmp_path / "operations.json"

    assert run_request_check(REPO_ROOT, REPO_ROOT / OPENAPI_RELATIVE_PATH, operations_file) == pytest.ExitCode.OK
    operations = json.loads(operations_file.read_text())
    assert {"method": "GET", "path": "/api/apps", "parses_503": False} in operations

    findings = run_oasdiff(REPO_ROOT / OPENAPI_RELATIVE_PATH, FIXTURES / "v0.55.0-openapi.json", None, "test")
    blocking = select_client_findings(findings, operations)

    assert any(f["path"] == "/api/apps" and "`200` status" in f["text"] for f in blocking)


def test_finding_with_an_unreadable_status_blocks() -> None:
    finding = {
        "id": "response-required-property-removed",
        "level": 3,
        "section": "paths",
        "operation": "GET",
        "path": "/api/thing",
        "text": "removed the required property `b` in a phrasing this check doesn't know",
    }

    assert select_client_findings([finding], CALLS_THING_ONLY) == [finding]


def floor_repo(repo: GitRepo, head_required: list[str], floor_required: list[str]) -> None:
    """A repo whose v1.0.0 (schema 1) is the floor release, and whose HEAD serves schema 1 too."""
    repo.write(OPENAPI_RELATIVE_PATH, json.dumps(operation_spec({"200": object_with_ab(floor_required)})))
    write_schema(repo, 1)
    repo.commit("release")
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo.root, check=True, capture_output=True)
    repo.write(OPENAPI_RELATIVE_PATH, json.dumps(operation_spec({"200": object_with_ab(head_required)})))
    repo.write("CHANGELOG.md", "unreleased\n")  # so HEAD is a new commit even when the spec is unchanged
    repo.commit("head")


def stub_request_check(monkeypatch: pytest.MonkeyPatch, operations: list[dict[str, Any]]) -> None:
    """Replace the coverage-test subprocess with one that passes and writes ``operations``."""

    def passing_request_check(_repo_root: Path, _spec: Path, operations_file: Path) -> int:
        operations_file.write_text(json.dumps(operations))
        return 0

    monkeypatch.setattr(check_client_floor, "run_request_check", passing_request_check)


@needs_oasdiff
def test_main_fails_when_the_floor_lacks_a_field_the_client_requires(
    git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    floor_repo(git_repo, head_required=["a", "b"], floor_required=["a"])
    stub_request_check(monkeypatch, CALLS_THING_ONLY)

    assert main(git_repo.root, min_schema=1) == 1
    assert "GET /api/thing" in capsys.readouterr().err


@needs_oasdiff
def test_main_passes_when_the_floor_has_every_required_field(
    git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    floor_repo(git_repo, head_required=["a"], floor_required=["a"])
    stub_request_check(monkeypatch, CALLS_THING_ONLY)

    assert main(git_repo.root, min_schema=1) == 0


@needs_oasdiff
def test_main_fails_when_no_operations_were_written(
    git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty operations file would make the response check pass without checking anything."""
    floor_repo(git_repo, head_required=["a"], floor_required=["a"])
    stub_request_check(monkeypatch, [])

    assert main(git_repo.root, min_schema=1) == 1
    assert "wrote no operations" in capsys.readouterr().err


def test_main_fails_without_oasdiff(
    git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_schema(git_repo, 1)
    git_repo.commit("server at schema 1")
    monkeypatch.setattr(check_client_floor.shutil, "which", lambda _name: None)

    assert main(git_repo.root, min_schema=1) == 1
    assert "oasdiff not found" in capsys.readouterr().err


def test_main_fails_cleanly_when_the_schema_module_is_missing(
    git_repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    write_spec(git_repo, "head")
    git_repo.commit("no schema module")

    assert main(git_repo.root, min_schema=1) == 1
    assert "wire/src/hassette_wire/health.py is missing" in capsys.readouterr().err

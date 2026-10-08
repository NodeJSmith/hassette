#!/usr/bin/env -S uv run
"""Every-PR check: hassette-client works against the oldest server reporting its ``MIN_API_SCHEMA_VERSION``.

The floor release is the oldest ``v*`` tag whose ``hassette_wire.API_SCHEMA_VERSION`` is at least
``MIN_API_SCHEMA_VERSION`` (a tag without the constant counts as ``0``), or HEAD when no tag qualifies.
Against that release's ``openapi.json`` the check runs:

- the request checks of ``client/tests/test_openapi_coverage.py`` (route, method, query parameter), with
  ``HASSETTE_CLIENT_OPENAPI`` pointing at the floor spec;
- a reversed ``oasdiff`` run (HEAD as base, floor as revision) with no ignore file, blocking on
  ``FLOOR_BLOCKING_CHECK_IDS`` only for operations the client calls and statuses it parses as a model
  (2xx, plus 503 for the probe methods). The coverage test writes those operations to the file named by
  ``HASSETTE_CLIENT_OPERATIONS``, since ``tools/`` isn't importable where the client's tests run.

It runs in CI only (``.github/workflows/tests.yml``), not as a pre-push hook: it needs every release tag
and runs the client's test suite. Rationale: ``design/specs/127-hassette-client-transport/design.md``,
decisions D20 and D27.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from check_wire_compat import (
    ERR_LEVEL,
    OPENAPI_RELATIVE_PATH,
    REPO_ROOT,
    REVERSED_BLOCKING_CHECK_IDS,
    describe_finding_location,
    extract_tagged_openapi,
    list_release_tags,
    run_git,
    run_oasdiff,
)
from hassette_client import MIN_API_SCHEMA_VERSION

OPENAPI_ENV_VAR = "HASSETTE_CLIENT_OPENAPI"
"""Read by ``client/tests/test_openapi_coverage.py``."""

OPERATIONS_ENV_VAR = "HASSETTE_CLIENT_OPERATIONS"
"""Read by ``client/tests/test_openapi_coverage.py``, which writes the client's operations there."""

COVERAGE_TEST = "tests/test_openapi_coverage.py"
"""Relative to ``client/``, where the client's pytest configuration lives."""

SCHEMA_CONSTANT = "API_SCHEMA_VERSION"

SCHEMA_MODULE_RELATIVE_PATH = "wire/src/hassette_wire/health.py"
"""Where ``API_SCHEMA_VERSION`` is defined, at HEAD and at every tag that has it."""

STATUS_PATTERN = re.compile(r"`(?P<before>\d{3})` status|status `(?P<after>\d{3})`")
"""oasdiff 1.32.1 reports a response finding's status only in its text, phrased two ways: "from the
response with the `200` status" and "became optional for the status `422`"."""

FLOOR_BLOCKING_CHECK_IDS = REVERSED_BLOCKING_CHECK_IDS | {
    "response-property-type-changed",
    "response-property-became-nullable",
    "response-success-status-removed",
}
"""Reversed findings (HEAD as base, floor as revision) that mean the client can't parse what the floor release
sends: a required field missing or optional, a field of another type or possibly null, or no success response.
Wider than ``check_wire_compat``'s set, which guards adjacent releases rather than whether this client parses."""

FINAL_RELEASE_TAG = re.compile(r"v\d+\.\d+\.\d+")

OASDIFF_LABEL = "hassette-client vs its floor release"

BUMP_RULE = (
    "Raise hassette_wire.API_SCHEMA_VERSION and MIN_API_SCHEMA_VERSION as the MIN_API_SCHEMA_VERSION "
    "docstring (client/src/hassette_client/version.py) describes."
)


def schema_version_in(source: str) -> int:
    """The module-level ``API_SCHEMA_VERSION`` in ``source``, or ``0`` when there is none.

    Raises:
        RuntimeError: The constant is assigned something other than an int literal, which this check
            can't read and mustn't guess at.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == SCHEMA_CONSTANT for target in targets):
            continue
        if isinstance(value, ast.Constant) and type(value.value) is int:
            return value.value
        raise RuntimeError(f"{SCHEMA_CONSTANT} must be assigned an int literal, found: {ast.unparse(value)}")
    return 0


def schema_version_at(repo_root: Path, tag: str) -> int:
    """The ``API_SCHEMA_VERSION`` tag ``tag`` serves; ``0`` when the tag predates the constant or its file."""
    listing = run_git(repo_root, "ls-tree", "--name-only", tag, "--", SCHEMA_MODULE_RELATIVE_PATH)
    if listing.returncode != 0:
        raise RuntimeError(f"git ls-tree {tag} failed: {listing.stderr.strip()}")
    if not listing.stdout.strip():
        return 0
    blob = f"{tag}:{SCHEMA_MODULE_RELATIVE_PATH}"
    result = run_git(repo_root, "show", blob)
    if result.returncode != 0:
        raise RuntimeError(f"git show {blob} failed: {result.stderr.strip()}")
    return schema_version_in(result.stdout)


def history_problem(repo_root: Path) -> str | None:
    """Why the checkout can't show which release is the floor, or ``None`` when it can.

    A shallow or tagless checkout would otherwise look like "no release reports the minimum yet" and make
    the check pass against HEAD without checking anything.
    """
    shallow = run_git(repo_root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        return f"git rev-parse failed: {shallow.stderr.strip()}"
    if shallow.stdout.strip() == "true":
        return "The checkout is shallow; fetch the full history and tags (actions/checkout fetch-depth: 0)."
    if not list_release_tags(repo_root):
        return "No v* release tags are reachable from HEAD; fetch tags (git fetch --tags)."
    return None


@dataclass(frozen=True)
class Floor:
    """The release the client is checked against."""

    tag: str | None
    """The floor release's tag, or ``None`` when no release reports the minimum yet and HEAD stands in."""
    spec: Path
    """That release's ``openapi.json``."""


def find_floor_tag(repo_root: Path, min_schema: int) -> str | None:
    """The oldest release tag reporting at least ``min_schema``, or ``None`` when no release does yet.

    Walks tags newest first and stops at the first one below ``min_schema``, which is sound because the bump
    rule only ever raises ``API_SCHEMA_VERSION``.

    Raises:
        RuntimeError: The walk reached a pre-release tag (KI-001,
            ``design/specs/127-hassette-client-transport/known-issues.md``).
    """
    floor_tag = None
    for tag in list_release_tags(repo_root):
        # git's version sort puts v1.2.0rc1 above v1.2.0, so a pre-release tagged before a schema bump would
        # end the walk early and pass against HEAD. Ordering them is unbuilt until pre-releases are cut.
        if FINAL_RELEASE_TAG.fullmatch(tag) is None:
            raise RuntimeError(
                f"The floor walk reached {tag}, which isn't a final vX.Y.Z release; this check doesn't order "
                "pre-release tags yet (KI-001, design/specs/127-hassette-client-transport/known-issues.md)."
            )
        if schema_version_at(repo_root, tag) < min_schema:
            break
        floor_tag = tag
    return floor_tag


def resolve_floor(repo_root: Path, min_schema: int, dest_dir: Path) -> Floor:
    """The floor release and its ``openapi.json``: its tag's copy, or HEAD's when no release qualifies.

    HEAD standing in makes the check pass trivially, since HEAD can't lack its own API; it lasts until a
    release reporting ``min_schema`` is cut.
    """
    tag = find_floor_tag(repo_root, min_schema)
    if tag is None:
        print(f"Floor release: HEAD (no release reports API schema {min_schema} yet)", flush=True)
        return Floor(tag=None, spec=repo_root / OPENAPI_RELATIVE_PATH)
    print(f"Floor release: {tag}", flush=True)
    return Floor(tag=tag, spec=extract_tagged_openapi(repo_root, tag, dest_dir))


def status_of(finding: dict[str, Any]) -> str | None:
    """The HTTP status a response finding is about, or ``None`` when its text doesn't say."""
    match = STATUS_PATTERN.search(finding["text"])
    if match is None:
        return None
    return match["before"] or match["after"]


def select_client_findings(findings: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``FLOOR_BLOCKING_CHECK_IDS`` findings on an operation the client calls, at a status it parses as a model."""
    parses_503_by_operation = {(op["method"], op["path"]): op["parses_503"] for op in operations}
    selected = []
    for finding in findings:
        if finding["id"] not in FLOOR_BLOCKING_CHECK_IDS or finding["level"] != ERR_LEVEL:
            continue
        key = (finding.get("operation"), finding.get("path"))
        if key not in parses_503_by_operation:
            continue
        status = status_of(finding)
        is_unreadable = status is None  # fail closed, so a new oasdiff phrasing can't silently pass
        is_success = status is not None and status.startswith("2")
        is_parsed_503 = status == "503" and parses_503_by_operation[key]
        if is_unreadable or is_success or is_parsed_503:
            selected.append(finding)
    return selected


def run_request_check(repo_root: Path, spec: Path, operations_file: Path) -> int:
    """Run the coverage test against ``spec``; it also writes the client's operations to ``operations_file``."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", COVERAGE_TEST],
        cwd=repo_root / "client",
        env={**os.environ, OPENAPI_ENV_VAR: str(spec), OPERATIONS_ENV_VAR: str(operations_file)},
        check=False,
    )
    if result.returncode == pytest.ExitCode.TESTS_FAILED:
        print(
            "The client coverage test failed against the floor release: either the client sends requests that "
            f"release doesn't serve, or a call no longer matches HEAD's spec (see the output above). {BUMP_RULE}",
            file=sys.stderr,
        )
    elif result.returncode != pytest.ExitCode.OK:
        print(f"The client coverage test didn't run cleanly (pytest exit {result.returncode}).", file=sys.stderr)
    return result.returncode


def preflight_problem(repo_root: Path, min_schema: int) -> str | None:
    """Why the check can't start, or ``None``: everything that needs neither git history nor the client's tests."""
    schema_module = repo_root / SCHEMA_MODULE_RELATIVE_PATH
    if not schema_module.exists():
        return f"{SCHEMA_MODULE_RELATIVE_PATH} is missing; update SCHEMA_MODULE_RELATIVE_PATH if it moved."
    try:
        head_schema = schema_version_in(schema_module.read_text())
    except RuntimeError as exc:
        return str(exc)
    if min_schema > head_schema:
        return (
            f"MIN_API_SCHEMA_VERSION is {min_schema}, above the API_SCHEMA_VERSION this checkout serves "
            f"({head_schema}). {BUMP_RULE}"
        )
    if shutil.which("oasdiff") is None:
        return "oasdiff not found on PATH. Install it with `mise install`."
    return None


def report_blocking(blocking: list[dict[str, Any]]) -> None:
    print(f"Client floor check FAILED ({OASDIFF_LABEL}):", file=sys.stderr)
    for finding in blocking:
        print(f"  [{finding['id']}] {describe_finding_location(finding)}: {finding['text']}", file=sys.stderr)
    print(f"hassette-client requires response fields its floor release doesn't send. {BUMP_RULE}", file=sys.stderr)


def main(repo_root: Path = REPO_ROOT, min_schema: int = MIN_API_SCHEMA_VERSION) -> int:
    problem = preflight_problem(repo_root, min_schema)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        operations_file = Path(tmp) / "operations.json"
        try:
            problem = history_problem(repo_root)
            if problem is not None:
                print(problem, file=sys.stderr)
                return 1
            floor = resolve_floor(repo_root, min_schema, Path(tmp))
            print(f"Checking hassette-client against {floor.spec} (MIN_API_SCHEMA_VERSION {min_schema})", flush=True)
            returncode = run_request_check(repo_root, floor.spec, operations_file)
            if returncode != pytest.ExitCode.OK:
                return returncode
            # A missing file and an empty one mean the same: the export test didn't record any calls.
            operations = json.loads(operations_file.read_text()) if operations_file.exists() else []
            if not operations:
                print("The client coverage test wrote no operations, so the response check can't run.", file=sys.stderr)
                return 1
            findings = run_oasdiff(repo_root / OPENAPI_RELATIVE_PATH, floor.spec, None, OASDIFF_LABEL)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            # A git or oasdiff failure, or a git call that hung.
            print(exc, file=sys.stderr)
            return 1

    blocking = select_client_findings(findings, operations)
    if blocking:
        report_blocking(blocking)
        return 1
    if floor.tag is None:
        print(f"hassette-client checked against HEAD only: no release reports API schema {min_schema} yet.")
    else:
        print(f"hassette-client works against its floor release, {floor.tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

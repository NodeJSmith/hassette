#!/usr/bin/env -S uv run
"""Every-PR check: hassette-client works against the oldest server reporting its ``MIN_API_SCHEMA_VERSION``.

The floor release is the oldest ``v*`` tag whose ``hassette_wire.API_SCHEMA_VERSION`` is at least
``MIN_API_SCHEMA_VERSION`` (a tag without the constant counts as ``0``), or HEAD when no tag qualifies.
Against that release's ``openapi.json`` the check runs:

- the request checks of ``client/tests/test_openapi_coverage.py`` (route, method, query parameter), with
  ``HASSETTE_CLIENT_OPENAPI`` pointing at the floor spec;
- a reversed ``oasdiff`` run (HEAD as base, floor as revision) with no ignore file, blocking on
  ``REVERSED_BLOCKING_CHECK_IDS`` only for operations the client calls and statuses it parses as a model
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
from pathlib import Path
from typing import Any

import pytest
from check_wire_compat import (
    GIT_TIMEOUT_SECONDS,
    OPENAPI_RELATIVE_PATH,
    REPO_ROOT,
    describe_finding_location,
    extract_tagged_openapi,
    list_release_tags,
    run_oasdiff,
    select_reversed_blocking_findings,
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

STATUS_PATTERN = re.compile(r"`(\d{3})` status|status `(\d{3})`")
"""oasdiff 1.32.1 reports a response finding's status only in its text, phrased two ways: "from the
response with the `200` status" and "became optional for the status `422`"."""

OASDIFF_LABEL = "hassette-client vs its floor release"

BUMP_RULE = (
    "Raise hassette_wire.API_SCHEMA_VERSION and MIN_API_SCHEMA_VERSION as the MIN_API_SCHEMA_VERSION "
    "docstring (client/src/hassette_client/version.py) describes."
)


def schema_version_in(source: str) -> int:
    """The module-level ``API_SCHEMA_VERSION = <int>`` in ``source``, or ``0`` when there is none."""
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == SCHEMA_CONSTANT for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, int)
        ):
            return node.value.value
    return 0


def schema_version_at(repo_root: Path, tag: str) -> int:
    """The ``API_SCHEMA_VERSION`` tag ``tag`` serves; ``0`` when the tag predates the constant or its file."""
    blob = f"{tag}:{SCHEMA_MODULE_RELATIVE_PATH}"
    exists = subprocess.run(
        ["git", "cat-file", "-e", blob], cwd=repo_root, capture_output=True, timeout=GIT_TIMEOUT_SECONDS
    )
    if exists.returncode != 0:
        return 0
    result = subprocess.run(
        ["git", "show", blob], cwd=repo_root, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS
    )
    if result.returncode != 0:
        raise RuntimeError(f"git show {blob} failed: {result.stderr.strip()}")
    return schema_version_in(result.stdout)


def resolve_floor_openapi(repo_root: Path, min_schema: int, dest_dir: Path) -> Path:
    """Return the floor release's ``openapi.json``: its tag's copy, or HEAD's when no tag qualifies.

    Stops at the first tag below ``min_schema``, which is sound because the bump rule only ever raises
    ``API_SCHEMA_VERSION``. HEAD's spec stands in until a release reporting ``min_schema`` is cut, which
    makes the check pass trivially: HEAD can't lack its own API.
    """
    floor_tag = None
    for tag in list_release_tags(repo_root):
        if schema_version_at(repo_root, tag) < min_schema:
            break
        floor_tag = tag
    if floor_tag is None:
        return repo_root / OPENAPI_RELATIVE_PATH
    print(f"Floor release: {floor_tag}", flush=True)
    return extract_tagged_openapi(repo_root, floor_tag, dest_dir)


def status_of(finding: dict[str, Any]) -> str | None:
    """The HTTP status a response finding is about, or ``None`` when its text doesn't say."""
    match = STATUS_PATTERN.search(finding["text"])
    if match is None:
        return None
    return match.group(1) or match.group(2)


def select_client_findings(findings: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blocking reversed findings on an operation the client calls, at a status it parses as a model.

    A finding whose status can't be read blocks too, so a new oasdiff phrasing can't silently pass.
    """
    parses_503_by_operation = {(op["method"], op["path"]): op["parses_503"] for op in operations}
    selected = []
    for finding in select_reversed_blocking_findings(findings):
        key = (finding.get("operation"), finding.get("path"))
        if key not in parses_503_by_operation:
            continue
        status = status_of(finding)
        is_success = status is not None and status.startswith("2")
        is_parsed_503 = status == "503" and parses_503_by_operation[key]
        if status is None or is_success or is_parsed_503:
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


def main(repo_root: Path = REPO_ROOT, min_schema: int = MIN_API_SCHEMA_VERSION) -> int:
    head_schema = schema_version_in((repo_root / SCHEMA_MODULE_RELATIVE_PATH).read_text())
    if min_schema > head_schema:
        print(
            f"MIN_API_SCHEMA_VERSION is {min_schema}, above the API_SCHEMA_VERSION this checkout serves "
            f"({head_schema}). {BUMP_RULE}",
            file=sys.stderr,
        )
        return 1
    if shutil.which("oasdiff") is None:
        print("oasdiff not found on PATH. Install it with `mise install`.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        operations_file = Path(tmp) / "operations.json"
        try:
            spec = resolve_floor_openapi(repo_root, min_schema, Path(tmp))
            print(f"Checking hassette-client against {spec} (MIN_API_SCHEMA_VERSION {min_schema})", flush=True)
            returncode = run_request_check(repo_root, spec, operations_file)
            if returncode != pytest.ExitCode.OK:
                return returncode
            operations = json.loads(operations_file.read_text()) if operations_file.exists() else []
            if not operations:
                print("The client coverage test wrote no operations, so the response check can't run.", file=sys.stderr)
                return 1
            findings = run_oasdiff(repo_root / OPENAPI_RELATIVE_PATH, spec, None, OASDIFF_LABEL)
        except RuntimeError as exc:
            # A git or oasdiff failure, raised by the check_wire_compat helpers or schema_version_at.
            print(exc, file=sys.stderr)
            return 1

    blocking = select_client_findings(findings, operations)
    if blocking:
        print(f"Client floor check FAILED ({OASDIFF_LABEL}):", file=sys.stderr)
        for finding in blocking:
            print(f"  [{finding['id']}] {describe_finding_location(finding)}: {finding['text']}", file=sys.stderr)
        print(f"hassette-client requires response fields its floor release doesn't send. {BUMP_RULE}", file=sys.stderr)
        return 1
    print("hassette-client works against its floor release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""CI guard: detect local test factories that shadow a shared factory.

The test suite has a shared factory registry (``hassette.test_utils.factories``,
the ``web_*_helpers`` modules, ``helpers``) built to absorb the same handful of conceptual
objects — ``ScheduledJob``, ``Event``, a mock ``CommandExecutor`` — that kept
getting hand-rolled again in each new test file. Left unchecked, an LLM (or a
developer in a hurry) reinvents the same ``make_*`` function in a new file
instead of importing the shared one, and the duplication compounds silently.

Detection is name-based, not import-based: any ``def``/``async def`` reachable from
module scope without crossing a class or function boundary — including one nested
inside an ``if``/``try``/``with`` block — is flagged if its name matches a key in
``SHARED_FACTORIES``, whether or not the file also imports the real thing. A name
match is the primary signal — an LLM writing a brand-new duplicate has no import to
check against, so waiting for one would miss exactly the case this guard exists to
catch. Class methods and functions nested inside another function are never
flagged — a method or closure named ``noop`` isn't importable as a drop-in
replacement for the shared factory, so it carries none of the duplication risk this
guard polices.

The ``# factory-local:`` annotation is the escape hatch for local factories that
legitimately share a name with a registry entry but build something different
(e.g. a ``make_job()`` that returns a ``MagicMock`` instead of a real
``ScheduledJob``). It requires a non-empty reason and must appear on the same
physical line as the ``def``/``async def`` keyword — unlike a lazy import, a
factory definition's signature can span many lines, so anchoring to the exact
``def`` line (rather than the whole span) keeps the exemption unambiguous.

Canonical annotation form: ``# factory-local: <reason>``

Usage:
    python tools/check_test_factories.py [FILE ...]

With no arguments, scans every file under tests/. Given file paths (as
pre-commit passes the staged files), scans only those — out-of-scope or
non-Python paths are ignored. Only tests/ is scanned; the shared factories
themselves live in src/ and are not subject to this check.
"""

import ast
import re
import sys
from pathlib import Path

from lint_helpers import REPO_ROOT, iter_python_files, run_check

SCAN_DIRS = ["tests"]

# Maps a shared factory's name to the module it lives in. Adding a new shared
# factory to test_utils means adding one line here.
SHARED_FACTORIES = {
    "make_scheduled_job": "hassette.test_utils.factories",
    "make_mock_executor": "hassette.test_utils.factories",
    "make_mock_event": "hassette.test_utils.factories",
    "make_recording_api": "hassette.test_utils.factories",
    "make_hassette_event": "hassette.test_utils.factories",
    "make_hass_event": "hassette.test_utils.factories",
    "make_mock_parent": "hassette.test_utils.factories",
    "make_invoke_handler_cmd": "hassette.test_utils.factories",
    "make_mock_listener": "hassette.test_utils.factories",
    "make_scheduler": "hassette.test_utils.factories",
    "make_execution_record": "hassette.test_utils.factories",
    "make_manifest": "hassette.test_utils.web_manifest_helpers",
    "make_full_snapshot": "hassette.test_utils.web_manifest_helpers",
    "make_manifest_response": "hassette.test_utils.web_manifest_helpers",
    "make_manifest_list_response": "hassette.test_utils.web_manifest_helpers",
    "make_job": "hassette.test_utils.web_job_helpers",
    "make_real_job": "hassette.test_utils.web_job_helpers",
    "make_job_summary": "hassette.test_utils.web_job_helpers",
    "make_system_status_response": "hassette.test_utils.web_response_helpers",
    "make_telemetry_status_response": "hassette.test_utils.web_response_helpers",
    "make_dashboard_app_grid_entry": "hassette.test_utils.web_response_helpers",
    "make_dashboard_app_grid_response": "hassette.test_utils.web_response_helpers",
    "make_config_schema_response": "hassette.test_utils.web_response_helpers",
    "make_app_health_response": "hassette.test_utils.web_response_helpers",
    "make_app_config_response": "hassette.test_utils.web_response_helpers",
    "make_app_source_response": "hassette.test_utils.web_response_helpers",
    "make_activity_feed_entry": "hassette.test_utils.web_telemetry_helpers",
    "make_listener_with_summary": "hassette.test_utils.web_telemetry_helpers",
    "make_execution": "hassette.test_utils.web_telemetry_helpers",
    "make_log_entry_response": "hassette.test_utils.web_telemetry_helpers",
    "make_logs_by_execution_response": "hassette.test_utils.web_telemetry_helpers",
    "make_crashed_event": "hassette.test_utils.helpers",
    "make_task_bucket": "hassette.test_utils.helpers",
    "async_noop": "hassette.test_utils.helpers",
    "noop": "hassette.test_utils.helpers",
}

ANNOTATION = "# factory-local:"

# Matches the annotation followed by a non-empty reason (at least one
# non-whitespace character after the colon).
ANNOTATION_RE = re.compile(r"#\s*factory-local:\s*\S")


def _collect_module_level_shadows(node: ast.AST, flagged: list[tuple[str, int]] | None = None) -> list[tuple[str, int]]:
    """Collect (name, lineno) for function defs reachable from module scope matching a
    registry name, without crossing a class or function boundary.

    Descends into compound statements (``if``/``try``/``with``/``for``/...) since a ``def``
    inside one is still bound at module level and just as importable as a bare top-level
    ``def``. Stops at ``ClassDef`` and ``FunctionDef``/``AsyncFunctionDef`` bodies -- a class
    method or a closure nested inside another function shares the module's function-definition
    syntax but not its shadowing risk, since neither is importable as a top-level replacement
    for the shared factory.
    """
    flagged = [] if flagged is None else flagged
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if child.name in SHARED_FACTORIES:
                flagged.append((child.name, child.lineno))
            continue
        if isinstance(child, ast.ClassDef):
            continue
        _collect_module_level_shadows(child, flagged)
    return flagged


def is_exempt(lines: list[str], lineno: int) -> bool:
    """Return True if the def's own line (1-based) carries a non-empty defend comment."""
    line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
    return bool(ANNOTATION_RE.search(line))


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, message) for un-exempt factory shadows."""
    source = path.read_text()
    lines = source.splitlines()
    flagged = _collect_module_level_shadows(ast.parse(source))

    violations = [
        (lineno, f"Local '{name}()' shadows shared factory — use 'from {SHARED_FACTORIES[name]} import {name}'")
        for name, lineno in flagged
        if not is_exempt(lines, lineno)
    ]
    return sorted(violations)


def iter_paths() -> list[Path]:
    """Return every .py file under tests/, sorted for stable output.

    The full-scan entry point the characterization tests parametrize over; ``main`` calls
    ``iter_python_files`` directly so a pre-commit run can scan just the staged files. Both go
    through ``iter_python_files``, so the full-scan path can't drift from the per-file path.
    """
    return iter_python_files([], SCAN_DIRS)


def main() -> int:
    return run_check(
        iter_python_files(sys.argv[1:], SCAN_DIRS),
        REPO_ROOT,
        check_file,
        summary="local test factory/factories shadow a shared factory",
        ok="no local factories shadow a shared test factory.",
        footer=(
            "Import the shared factory instead of redefining it. If the local version\n"
            "genuinely builds something different, annotate the 'def' line: "
            "'# factory-local: <reason>' (the reason is required)."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())

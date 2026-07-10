#!/usr/bin/env python3
"""CI guard: detect local test factories that shadow a shared factory.

The test suite has a shared factory registry (``hassette.test_utils.factories``,
``web_helpers``, ``helpers``) built to absorb the same handful of conceptual
objects — ``ScheduledJob``, ``Event``, a mock ``CommandExecutor`` — that kept
getting hand-rolled again in each new test file. Left unchecked, an LLM (or a
developer in a hurry) reinvents the same ``make_*`` function in a new file
instead of importing the shared one, and the duplication compounds silently.

Detection is name-based, not import-based: any ``def``/``async def`` whose name
matches a key in ``SHARED_FACTORIES`` is flagged, whether or not the file also
imports the real thing. A name match is the primary signal — an LLM writing a
brand-new duplicate has no import to check against, so waiting for one would
miss exactly the case this guard exists to catch.

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
    "make_mock_parent": "hassette.test_utils.factories",
    "make_invoke_handler_cmd": "hassette.test_utils.factories",
    "make_manifest": "hassette.test_utils.web_helpers",
    "noop": "hassette.test_utils.helpers",
}

ANNOTATION = "# factory-local:"

# Matches the annotation followed by a non-empty reason (at least one
# non-whitespace character after the colon).
ANNOTATION_RE = re.compile(r"#\s*factory-local:\s*\S")


class FactoryVisitor(ast.NodeVisitor):
    """Collect (name, lineno) for every function definition matching a registry name."""

    def __init__(self) -> None:
        self.flagged: list[tuple[str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name in SHARED_FACTORIES:
            self.flagged.append((node.name, node.lineno))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name in SHARED_FACTORIES:
            self.flagged.append((node.name, node.lineno))
        self.generic_visit(node)


def is_exempt(lines: list[str], lineno: int) -> bool:
    """Return True if the def's own line (1-based) carries a non-empty defend comment."""
    line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
    return bool(ANNOTATION_RE.search(line))


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted list of (1-based line number, message) for un-exempt factory shadows."""
    source = path.read_text()
    lines = source.splitlines()
    visitor = FactoryVisitor()
    visitor.visit(ast.parse(source))

    violations = [
        (lineno, f"Local '{name}()' shadows shared factory — use 'from {SHARED_FACTORIES[name]} import {name}'")
        for name, lineno in visitor.flagged
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

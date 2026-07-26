#!/usr/bin/env -S uv run
"""CI/pre-push check: detect hassette CLI surface drift.

Regenerates two "CLI shape" snapshots in memory and compares them against the
committed baselines in ``tests/snapshots/``:

- ``cli_help.txt`` — ``--help`` output for every command and subcommand,
  captured in-process via cyclopts (no subprocess, no running instance).
- ``cli_columns.json`` — the ``Column(...)`` table definitions declared in
  ``hassette.cli.commands.*``, serialized field-by-field.

A mismatch means the CLI surface changed (new command, renamed flag, changed
help text, added/removed/renamed table column) without the docs being
updated to match. This catches the common case cheaply; pure formatting
changes in ``output.py`` that don't change any signature are not caught
here — those are expected to surface during normal doc maintenance instead
(currently a manual doc edit; see #855 for tracked Cog-based automation).

Usage:
    uv run python tools/check_cli_drift.py            # check (default)
    uv run python tools/check_cli_drift.py --check     # check, explicit
    uv run python tools/check_cli_drift.py --update    # write fresh snapshots
"""

import argparse
import difflib
import importlib
import io
import json
import pkgutil
import sys
from pathlib import Path

from cyclopts import App as CycloptsApp
from rich.console import Console

import hassette.cli.commands as commands_pkg
from hassette.cli import app as root_app
from hassette.cli.output import Column

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = REPO_ROOT / "tests" / "snapshots"
HELP_SNAPSHOT = SNAPSHOT_DIR / "cli_help.txt"
COLUMNS_SNAPSHOT = SNAPSHOT_DIR / "cli_columns.json"

# Fixed so the snapshot doesn't depend on the invoking terminal's width.
HELP_CONSOLE_WIDTH = 100


def discover_command_paths() -> list[tuple[str, ...]]:
    """Return every command path (including the root) as a sorted list of tuples.

    Walks the cyclopts command tree (``App.resolved_commands()``) recursively.
    Flag-like entries (``--help``, ``-h``, ``--version``, etc.) are not real
    subcommands and are skipped.
    """

    def walk(node: CycloptsApp, prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
        paths = []
        for name, sub in node.resolved_commands().items():
            if name.startswith("-"):
                continue
            path = (*prefix, name)
            paths.append(path)
            paths.extend(walk(sub, path))
        return paths

    return sorted([(), *walk(root_app, ())])


def build_help_snapshot() -> str:
    """Render ``--help`` for every discovered command path, in-process.

    Trailing whitespace is stripped per line — Rich right-pads wrapped
    description text to the console width, which the repo's trailing-whitespace
    hook would otherwise strip back out from the committed file, and any
    ``--update`` run would then never produce a byte-identical result.
    """
    sections = []
    for path in discover_command_paths():
        buf = io.StringIO()
        console = Console(file=buf, no_color=True, width=HELP_CONSOLE_WIDTH, highlight=False, legacy_windows=False)
        root_app.help_print(list(path), console=console)
        rendered = "\n".join(line.rstrip() for line in buf.getvalue().splitlines())
        label = "hassette " + " ".join((*path, "--help"))
        sections.append(f"$ {label}\n{rendered}\n")
    return "\n".join(sections)


def build_columns_snapshot() -> dict[str, dict[str, list[dict[str, object]]]]:
    """Serialize every module-level ``list[Column]`` in ``hassette.cli.commands.*``."""
    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for module_info in sorted(pkgutil.iter_modules(commands_pkg.__path__), key=lambda m: m.name):
        if module_info.name == "__init__":
            continue
        module = importlib.import_module(f"{commands_pkg.__name__}.{module_info.name}")
        module_columns = {}
        for name in sorted(vars(module)):
            value = getattr(module, name)
            if isinstance(value, list) and value and all(isinstance(v, Column) for v in value):
                module_columns[name] = [
                    {
                        "field": col.field,
                        "header": col.header,
                        "max_width": col.max_width,
                        "overflow": col.overflow,
                        "formatter": col.formatter.__name__ if col.formatter is not None else None,
                    }
                    for col in value
                ]
        if module_columns:
            result[module_info.name] = module_columns
    return result


def unified_diff(label: str, committed: str, current: str) -> str:
    diff = difflib.unified_diff(
        committed.splitlines(keepends=True),
        current.splitlines(keepends=True),
        fromfile=f"{label} (committed)",
        tofile=f"{label} (current)",
    )
    return "".join(diff)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect hassette CLI surface drift (help text, table columns).")
    mode = parser.add_mutually_exclusive_group()
    # --check is the implicit default (see the `if args.update` branch below); accepted
    # explicitly too so `--check` reads clearly in docs and CI invocations.
    mode.add_argument("--check", action="store_true", help="Check snapshots match the current CLI surface (default).")
    mode.add_argument("--update", action="store_true", help="Write fresh snapshots to disk.")
    args = parser.parse_args()

    help_text = build_help_snapshot()
    columns_json = json.dumps(build_columns_snapshot(), indent=2, sort_keys=True) + "\n"

    if args.update:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        HELP_SNAPSHOT.write_text(help_text, encoding="utf-8")
        COLUMNS_SNAPSHOT.write_text(columns_json, encoding="utf-8")
        print(f"Updated {HELP_SNAPSHOT.relative_to(REPO_ROOT)} and {COLUMNS_SNAPSHOT.relative_to(REPO_ROOT)}")
        return 0

    problems: list[str] = []

    for snapshot, label, expected in [
        (HELP_SNAPSHOT, "cli_help.txt", help_text),
        (COLUMNS_SNAPSHOT, "cli_columns.json", columns_json),
    ]:
        if not snapshot.exists():
            problems.append(f"{snapshot.relative_to(REPO_ROOT)} does not exist")
        elif (committed := snapshot.read_text(encoding="utf-8")) != expected:
            problems.append(unified_diff(label, committed, expected))

    if problems:
        print("CLI surface drift detected:\n")
        print("\n".join(problems))
        print("Re-run: uv run python tools/check_cli_drift.py --update")
        print("Then update docs/pages/cli/commands.md and docs/pages/cli/index.md to match.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

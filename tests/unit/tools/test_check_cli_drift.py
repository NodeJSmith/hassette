"""Characterization tests for tools/check_cli_drift.py.

Command/column discovery is exercised against the real ``hassette.cli`` package
(spot-checked for known, stable entries) since that introspection is the point of
the tool. The ``--check``/``--update`` CLI flow is isolated from the real CLI
surface via monkeypatched snapshot builders so it stays fast and immune to CLI
surface changes elsewhere in the codebase.
"""

import sys
from pathlib import Path

import check_cli_drift
import pytest
from check_cli_drift import (
    build_columns_snapshot,
    build_help_snapshot,
    discover_command_paths,
    main,
    unified_diff,
)


def test_discover_command_paths_includes_known_commands() -> None:
    paths = discover_command_paths()

    assert () in paths
    assert ("app",) in paths
    assert ("app", "health") in paths
    assert ("job",) in paths
    assert paths == sorted(paths)


def test_discover_command_paths_excludes_flag_like_entries() -> None:
    paths = discover_command_paths()

    assert not any(segment.startswith("-") for path in paths for segment in path)


def test_build_help_snapshot_is_deterministic_and_covers_known_commands() -> None:
    first = build_help_snapshot()
    second = build_help_snapshot()

    assert first == second
    assert "$ hassette --help" in first
    assert "$ hassette app health --help" in first


def test_build_columns_snapshot_includes_known_module_and_column() -> None:
    columns = build_columns_snapshot()

    assert "job" in columns
    assert "JOB_LIST_COLUMNS" in columns["job"]
    fields = [col["field"] for col in columns["job"]["JOB_LIST_COLUMNS"]]
    assert "app_key" in fields


def test_build_columns_snapshot_serializes_formatter_by_name() -> None:
    columns = build_columns_snapshot()

    avg_col = next(col for col in columns["job"]["JOB_LIST_COLUMNS"] if col["field"] == "avg_duration_ms")
    assert avg_col["formatter"] == "fmt_duration_ms"

    id_col = next(col for col in columns["job"]["JOB_LIST_COLUMNS"] if col["field"] == "job_id")
    assert id_col["formatter"] is None


def test_unified_diff_empty_when_equal() -> None:
    assert unified_diff("label", "same\n", "same\n") == ""


def test_unified_diff_reports_added_and_removed_lines() -> None:
    diff = unified_diff("cli_help.txt", "old line\n", "new line\n")

    assert "cli_help.txt (committed)" in diff
    assert "cli_help.txt (current)" in diff
    assert "-old line" in diff
    assert "+new line" in diff


@pytest.fixture
def isolated_snapshots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the module's snapshot paths at tmp_path and stub the (slow, live) builders."""
    monkeypatch.setattr(check_cli_drift, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_cli_drift, "HELP_SNAPSHOT", tmp_path / "cli_help.txt")
    monkeypatch.setattr(check_cli_drift, "COLUMNS_SNAPSHOT", tmp_path / "cli_columns.json")
    monkeypatch.setattr(check_cli_drift, "build_help_snapshot", lambda: "help-text-v1\n")
    monkeypatch.setattr(check_cli_drift, "build_columns_snapshot", lambda: {"mod": {"COLS": []}})


@pytest.mark.usefixtures("isolated_snapshots")
def test_main_check_fails_when_snapshots_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["check_cli_drift.py", "--check"])

    assert main() == 1
    out = capsys.readouterr().out
    assert "does not exist" in out


@pytest.mark.usefixtures("isolated_snapshots")
def test_main_update_then_check_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["check_cli_drift.py", "--update"])
    assert main() == 0

    monkeypatch.setattr(sys, "argv", ["check_cli_drift.py", "--check"])
    assert main() == 0


@pytest.mark.usefixtures("isolated_snapshots")
def test_main_check_fails_on_drift(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["check_cli_drift.py", "--update"])
    assert main() == 0

    # Simulate an intentional CLI change that wasn't followed by --update.
    monkeypatch.setattr(check_cli_drift, "build_help_snapshot", lambda: "help-text-v2\n")

    monkeypatch.setattr(sys, "argv", ["check_cli_drift.py", "--check"])
    assert main() == 1
    out = capsys.readouterr().out
    assert "-help-text-v1" in out
    assert "+help-text-v2" in out
    assert "Re-run: uv run python tools/check_cli_drift.py --update" in out

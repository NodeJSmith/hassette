"""Unit tests for the execution-history columns shared by ``hassette job <id>`` and ``hassette listener <id>``."""

from hassette.cli.commands.executions import EXECUTION_HISTORY_COLUMNS


def test_execution_history_columns_defined() -> None:
    """EXECUTION_HISTORY_COLUMNS includes key execution fields."""
    field_names = [c.field for c in EXECUTION_HISTORY_COLUMNS]
    assert "status" in field_names
    assert "duration_ms" in field_names
    assert "execution_start_ts" in field_names
    assert "error_type" in field_names


def test_execution_history_columns_count_is_compact() -> None:
    """EXECUTION_HISTORY_COLUMNS uses at most 7 columns for 80-column fit."""
    assert len(EXECUTION_HISTORY_COLUMNS) <= 7

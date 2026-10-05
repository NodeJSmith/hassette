"""SQL CHECK constraints that list a wire vocabulary's values must list exactly those values.

Typed wire fields parse strictly on the server, so a stored value outside the vocabulary fails the
whole response, and a vocabulary value the column rejects can never be persisted.
"""

import re
from enum import StrEnum
from typing import Any, get_args

import pytest
from hassette_wire import (
    BackpressurePolicy,
    BlockingTier,
    ExecutionMode,
    ExecutionStatus,
    ScheduleStatus,
    ScheduleStatusReason,
    SourceTier,
)
from hassette_wire.literals import ExecutionKind

from hassette.core.migration_runner import run_migrations
from tests.support.sql import sqlite_conn

# Matches every ``<column> IN ('a', 'b')`` in a table's SQL, wherever it sits inside its CHECK clause.
IN_LIST = re.compile(r"\b(\w+)\s+IN\s*\(([^)]*)\)")

WIRE_VOCABULARY_COLUMNS: dict[tuple[str, str], Any] = {
    ("scheduled_jobs", "schedule_status"): ScheduleStatus,
    ("scheduled_jobs", "schedule_status_reason"): ScheduleStatusReason,
    ("scheduled_jobs", "mode"): ExecutionMode,
    ("scheduled_jobs", "source_tier"): SourceTier,
    ("listeners", "mode"): ExecutionMode,
    ("listeners", "backpressure"): BackpressurePolicy,
    ("listeners", "source_tier"): SourceTier,
    ("executions", "status"): ExecutionStatus,
    ("executions", "kind"): ExecutionKind,
    ("executions", "source_tier"): SourceTier,
    ("blocking_events", "tier"): BlockingTier,
    ("blocking_events", "source_tier"): SourceTier,
}

# Constrained columns with no wire vocabulary of the same values, and why.
SERVER_ONLY_COLUMNS: dict[tuple[str, str], str] = {
    ("sessions", "status"): "session status is not served over the wire",
    ("scheduled_jobs", "trigger_type"): "trigger type is not served as a vocabulary",
    ("blocking_events", "reason"): "also holds 'attributed'; UnattributedReason covers only unattributed stalls",
}


def vocabulary_values(vocabulary: Any) -> set[str]:
    """Values of a wire ``StrEnum`` or ``Literal``."""
    if isinstance(vocabulary, type) and issubclass(vocabulary, StrEnum):
        return {member.value for member in vocabulary}
    return set(get_args(vocabulary))


@pytest.fixture(scope="module")
def in_list_checks(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, str, set[str]]]:
    """(table, column, values) for every IN-list CHECK in the fully migrated schema."""
    db_path = tmp_path_factory.mktemp("parity") / "parity.db"
    run_migrations(db_path)
    with sqlite_conn(db_path) as conn:
        rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL").fetchall()
    return [
        (table, column, {value.strip().strip("'") for value in values.split(",")})
        for table, sql in rows
        for column, values in IN_LIST.findall(sql)
    ]


@pytest.fixture(scope="module")
def check_constraints(in_list_checks: list[tuple[str, str, set[str]]]) -> dict[tuple[str, str], set[str]]:
    """(table, column) -> values; each column has one IN-list (see test_each_column_has_one_in_list)."""
    return {(table, column): values for table, column, values in in_list_checks}


def test_each_column_has_one_in_list(in_list_checks: list[tuple[str, str, set[str]]]) -> None:
    """A second IN-list on the same column would make check_constraints compare against only one of them."""
    keys = [(table, column) for table, column, _ in in_list_checks]
    duplicates = {key for key in keys if keys.count(key) > 1}

    assert not duplicates, f"columns with more than one IN-list CHECK: {sorted(duplicates)}"


def test_every_in_list_check_is_classified(check_constraints: dict[tuple[str, str], set[str]]) -> None:
    classified = WIRE_VOCABULARY_COLUMNS.keys() | SERVER_ONLY_COLUMNS.keys()

    assert not check_constraints.keys() - classified, "IN-list CHECK not classified as wire vocabulary or server-only"
    assert not classified - check_constraints.keys(), "classified column has no IN-list CHECK in the migrated schema"


@pytest.mark.parametrize(
    ("table", "column"), list(WIRE_VOCABULARY_COLUMNS), ids=[f"{t}.{c}" for t, c in WIRE_VOCABULARY_COLUMNS]
)
def test_check_values_equal_wire_vocabulary(
    check_constraints: dict[tuple[str, str], set[str]], table: str, column: str
) -> None:
    assert check_constraints[(table, column)] == vocabulary_values(WIRE_VOCABULARY_COLUMNS[(table, column)])

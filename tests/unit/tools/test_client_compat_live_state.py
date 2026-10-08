"""Tests for tools/client_compat_live_state.py: what it adds to a seeded database and reads back from it."""

import sqlite3
from pathlib import Path

import uuid_utils
from client_compat_live_state import live_manifests, read_seed_ids, seed_live_state, uuid7_at
from hassette_wire import ExecutionStatus
from seed_db import generate_scenario


def seeded(tmp_path: Path, scenario: str) -> Path:
    db_path = tmp_path / f"{scenario}.db"
    generate_scenario(scenario, output_path=db_path, tmp_path=tmp_path / f"{scenario}.db.tmp")
    seed_live_state(db_path, live_manifests())
    return db_path


def test_uuid7_at_embeds_the_timestamp() -> None:
    parsed = uuid_utils.UUID(uuid7_at(1768494780.25))

    assert parsed.version == 7
    assert parsed.timestamp == 1768494780250


def test_seed_live_state_links_logs_and_blocking_events_to_a_failed_uuid_execution(tmp_path: Path) -> None:
    ids = read_seed_ids(seeded(tmp_path, "healthy"))

    assert ids.logged_execution_id is not None
    assert ids.failed_execution_id == ids.logged_execution_id
    assert ids.multi_app_listed
    conn = sqlite3.connect(tmp_path / "healthy.db")
    try:
        status, traceback = conn.execute(
            "SELECT status, error_traceback FROM executions WHERE execution_id = ?", (ids.failed_execution_id,)
        ).fetchone()
        linked_blocking = conn.execute(
            "SELECT COUNT(*) FROM blocking_events WHERE execution_id = ? AND frames IS NOT NULL",
            (ids.failed_execution_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == ExecutionStatus.ERROR
    assert traceback
    assert linked_blocking == 2


def test_seed_live_state_leaves_a_database_without_executions_as_seeded(tmp_path: Path) -> None:
    ids = read_seed_ids(seeded(tmp_path, "empty"))

    assert (ids.app_key, ids.logged_execution_id, ids.failed_execution_id) == (None, None, None)
    assert not ids.multi_app_listed

"""Unit tests for retention cleanup pruning ``app_manifests`` rows of apps removed from config."""

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from tests.support.helpers import create_app_manifest
from tests.support.sql import insert_execution_row

from ._fixtures_retention import db, make_failing_execute, mock_hassette_for_db, retention_service

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures

REMOVED_APP = "removed_app"
RECENT_TS = time.time() - 60
OLD_TS = time.time() - (30 * SECONDS_PER_DAY)


async def insert_manifest(db: aiosqlite.Connection, app_key: str) -> None:
    await db.execute("INSERT INTO app_manifests (app_key) VALUES (?)", (app_key,))
    await db.commit()


async def run_cleanup(db: aiosqlite.Connection, service: DatabaseService) -> None:
    """Commit seeded rows, then run one retention cycle."""
    await db.commit()
    await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]


async def count_rows(db: aiosqlite.Connection, table: str) -> int:
    cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
    row = await cursor.fetchone()
    assert row is not None
    return row[0]


async def manifest_exists(db: aiosqlite.Connection, app_key: str) -> bool:
    cursor = await db.execute("SELECT 1 FROM app_manifests WHERE app_key = ?", (app_key,))
    return await cursor.fetchone() is not None


async def insert_listener(db: aiosqlite.Connection, app_key: str, retired_at: float | None) -> int:
    cursor = await db.execute(
        "INSERT INTO listeners (app_key, instance_index, name, retired_at) VALUES (?, 1, 'l', ?)",
        (app_key, retired_at),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def seed_recent_execution(db: aiosqlite.Connection, app_key: str) -> None:
    """A retired listener whose execution is still inside retention, so the parent-guard keeps it."""
    listener_id = await insert_listener(db, app_key, retired_at=OLD_TS)
    await insert_execution_row(db, listener_id=listener_id, execution_start_ts=RECENT_TS)


async def insert_job(db: aiosqlite.Connection, app_key: str) -> int:
    cursor = await db.execute(
        "INSERT INTO scheduled_jobs (app_key, instance_index, job_name) VALUES (?, 1, 'j')", (app_key,)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def seed_recent_job_execution(db: aiosqlite.Connection, app_key: str) -> None:
    """An unretired job with an execution still inside retention."""
    job_id = await insert_job(db, app_key)
    await insert_execution_row(db, kind="job", job_id=job_id, execution_start_ts=RECENT_TS)


async def seed_recent_log_record(db: aiosqlite.Connection, app_key: str) -> None:
    await db.execute(
        "INSERT INTO log_records (seq, timestamp, level, logger_name, message, app_key, instance_index, source_tier) "
        "VALUES (1, ?, 'INFO', 'x', 'm', ?, 1, 'app')",
        (RECENT_TS, app_key),
    )


async def seed_recent_blocking_event(db: aiosqlite.Connection, app_key: str) -> None:
    await db.execute(
        "INSERT INTO blocking_events (app_key, instance_index, tier, detected_ts, source_tier) "
        "VALUES (?, 1, 'watchdog', ?, 'app')",
        (app_key, RECENT_TS),
    )


async def test_removed_app_without_telemetry_is_pruned(
    db: aiosqlite.Connection, retention_service: DatabaseService, caplog: pytest.LogCaptureFixture
) -> None:
    await insert_manifest(db, REMOVED_APP)

    with caplog.at_level(logging.INFO):
        await run_cleanup(db, retention_service)

    assert not await manifest_exists(db, REMOVED_APP)
    assert "Retention cleanup summary: deleted 1 removed app manifests" in caplog.text
    assert REMOVED_APP in caplog.text


async def test_app_in_current_config_is_never_pruned(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock, tmp_path: Path
) -> None:
    manifest = create_app_manifest("kept", tmp_path)
    mock_hassette_for_db.config.apps.manifests = {manifest.app_key: manifest}
    await insert_manifest(db, manifest.app_key)

    await run_cleanup(db, retention_service)

    assert await manifest_exists(db, manifest.app_key)


@pytest.mark.parametrize(
    "seed",
    [seed_recent_execution, seed_recent_job_execution, seed_recent_log_record, seed_recent_blocking_event],
    ids=["execution", "scheduled_job", "log_record", "blocking_event"],
)
async def test_removed_app_kept_while_telemetry_remains(
    db: aiosqlite.Connection,
    retention_service: DatabaseService,
    seed: Callable[[aiosqlite.Connection, str], Awaitable[None]],
) -> None:
    await insert_manifest(db, REMOVED_APP)
    await seed(db, REMOVED_APP)
    await run_cleanup(db, retention_service)

    assert await manifest_exists(db, REMOVED_APP)


async def test_removed_app_pruned_once_its_telemetry_ages_out_in_same_cycle(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    """Aged-out executions, then the retired listener, then the manifest all go in one cycle."""
    await insert_manifest(db, REMOVED_APP)
    listener_id = await insert_listener(db, REMOVED_APP, retired_at=OLD_TS)
    await insert_execution_row(db, listener_id=listener_id, execution_start_ts=OLD_TS)
    await run_cleanup(db, retention_service)

    assert not await manifest_exists(db, REMOVED_APP)


async def test_removed_app_unretired_registrations_are_kept(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    """During a hot reload a removed app runs until its orphan stop, with unretired rows.

    Retention must not infer retirement from config absence: the app lifecycle retires the rows
    once the app has stopped, and until then the rows (and so the manifest) stay.
    """
    await insert_manifest(db, REMOVED_APP)
    listener_id = await insert_listener(db, REMOVED_APP, retired_at=None)
    await insert_execution_row(db, listener_id=listener_id, execution_start_ts=OLD_TS)
    await insert_job(db, REMOVED_APP)
    await run_cleanup(db, retention_service)

    assert await count_rows(db, "listeners") == 1
    assert await count_rows(db, "scheduled_jobs") == 1
    assert await manifest_exists(db, REMOVED_APP)


async def test_configured_app_never_retired_registrations_are_kept(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock, tmp_path: Path
) -> None:
    manifest = create_app_manifest("kept", tmp_path)
    mock_hassette_for_db.config.apps.manifests = {manifest.app_key: manifest}
    await insert_manifest(db, manifest.app_key)
    await insert_listener(db, manifest.app_key, retired_at=None)
    await insert_job(db, manifest.app_key)
    await run_cleanup(db, retention_service)

    assert await count_rows(db, "listeners") == 1
    assert await count_rows(db, "scheduled_jobs") == 1


@pytest.mark.parametrize(
    "seed",
    [seed_recent_execution, seed_recent_job_execution, seed_recent_log_record, seed_recent_blocking_event],
    ids=["execution", "scheduled_job", "log_record", "blocking_event"],
)
async def test_other_apps_telemetry_does_not_block_pruning(
    db: aiosqlite.Connection,
    retention_service: DatabaseService,
    seed: Callable[[aiosqlite.Connection, str], Awaitable[None]],
) -> None:
    await insert_manifest(db, REMOVED_APP)
    await seed(db, "other_app")
    await run_cleanup(db, retention_service)

    assert not await manifest_exists(db, REMOVED_APP)


async def test_manifest_prune_skipped_when_a_target_failed(
    db: aiosqlite.Connection, retention_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    await insert_manifest(db, REMOVED_APP)
    monkeypatch.setattr(db, "execute", make_failing_execute(db, "DELETE FROM blocking_events"))

    await run_cleanup(db, retention_service)

    assert await manifest_exists(db, REMOVED_APP)

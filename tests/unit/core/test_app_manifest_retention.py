"""Unit tests for retention cleanup pruning ``app_manifests`` rows of apps removed from config."""

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.app_registry import AppRegistry
from hassette.core.database_service import DatabaseService
from tests.support.helpers import create_app_manifest
from tests.support.sql import count_rows, insert_execution_row

from ._fixtures_retention import db, make_failing_execute, mock_hassette_for_db, retention_service

__all__ = ["db", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures

REMOVED_APP = "removed_app"
RECENT_TS = time.time() - 60
# Past the default database.retention_days, so rows stamped with it are outside the window.
OLD_TS = time.time() - (30 * SECONDS_PER_DAY)


async def insert_manifest(db: aiosqlite.Connection, app_key: str) -> None:
    await db.execute("INSERT INTO app_manifests (app_key) VALUES (?)", (app_key,))
    await db.commit()


async def run_cleanup(db: aiosqlite.Connection, service: DatabaseService) -> None:
    """Commit seeded rows, then run one retention cycle."""
    await db.commit()
    await service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]


async def manifest_exists(db: aiosqlite.Connection, app_key: str) -> bool:
    cursor = await db.execute("SELECT 1 FROM app_manifests WHERE app_key = ?", (app_key,))
    return await cursor.fetchone() is not None


async def insert_listener(
    db: aiosqlite.Connection, app_key: str, retired_at: float | None, source_tier: str = "app"
) -> int:
    cursor = await db.execute(
        "INSERT INTO listeners (app_key, instance_index, name, retired_at, source_tier) VALUES (?, 1, 'l', ?, ?)",
        (app_key, retired_at, source_tier),
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


async def retired_at_values(db: aiosqlite.Connection, table: str) -> list[float | None]:
    cursor = await db.execute(f"SELECT retired_at FROM {table}")
    return [row[0] for row in await cursor.fetchall()]


async def test_removed_app_without_telemetry_is_pruned(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    await insert_manifest(db, REMOVED_APP)

    await run_cleanup(db, retention_service)

    assert not await manifest_exists(db, REMOVED_APP)


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


async def test_removed_app_registrations_are_retired_not_deleted(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    """A removed app is never reconciled again, so retention retires its rows itself.

    Also the state of an app mid-shutdown (``stop_app`` unregisters it before shutting it down):
    its rows are retired this cycle, not deleted, so they (and the manifest) stay until they age out.
    """
    await insert_manifest(db, REMOVED_APP)
    listener_id = await insert_listener(db, REMOVED_APP, retired_at=None)
    await insert_execution_row(db, listener_id=listener_id, execution_start_ts=OLD_TS)
    await insert_job(db, REMOVED_APP)
    await run_cleanup(db, retention_service)

    assert all(ts is not None for ts in await retired_at_values(db, "listeners"))
    assert all(ts is not None for ts in await retired_at_values(db, "scheduled_jobs"))
    assert await count_rows(db, "listeners") == 1
    assert await count_rows(db, "scheduled_jobs") == 1
    assert await manifest_exists(db, REMOVED_APP)


async def test_removed_app_still_running_keeps_unretired_registrations(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock
) -> None:
    """A hot reload swaps the config before stopping removed apps; a still-running app is live."""
    mock_hassette_for_db.app_handler.registry.app_keys.return_value = [REMOVED_APP]
    await insert_manifest(db, REMOVED_APP)
    await insert_listener(db, REMOVED_APP, retired_at=None)
    await insert_job(db, REMOVED_APP)
    await run_cleanup(db, retention_service)

    assert await retired_at_values(db, "listeners") == [None]
    assert await retired_at_values(db, "scheduled_jobs") == [None]


async def test_removed_app_still_running_without_telemetry_is_not_pruned(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock
) -> None:
    """Pruning a running app's manifest would hide rows it writes afterwards from retirement."""
    mock_hassette_for_db.app_handler.registry.app_keys.return_value = [REMOVED_APP]
    await insert_manifest(db, REMOVED_APP)

    await run_cleanup(db, retention_service)

    assert await manifest_exists(db, REMOVED_APP)


async def test_unwired_app_handler_falls_back_to_config_keys(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock, tmp_path: Path
) -> None:
    manifest = create_app_manifest("kept", tmp_path)
    mock_hassette_for_db.config.apps.manifests = {manifest.app_key: manifest}
    # The accessor is a property that raises when unwired; patch it on the mock's own class.
    type(mock_hassette_for_db).app_handler = PropertyMock(side_effect=RuntimeError("AppHandler not wired"))
    await insert_manifest(db, manifest.app_key)
    await insert_manifest(db, REMOVED_APP)

    await run_cleanup(db, retention_service)

    assert await manifest_exists(db, manifest.app_key)
    assert not await manifest_exists(db, REMOVED_APP)


async def test_configured_app_keeps_its_unretired_registrations(
    db: aiosqlite.Connection, retention_service: DatabaseService, mock_hassette_for_db: MagicMock, tmp_path: Path
) -> None:
    manifest = create_app_manifest("kept", tmp_path)
    mock_hassette_for_db.config.apps.manifests = {manifest.app_key: manifest}
    await insert_manifest(db, manifest.app_key)
    await insert_listener(db, manifest.app_key, retired_at=None)
    await insert_job(db, manifest.app_key)
    await run_cleanup(db, retention_service)

    assert await retired_at_values(db, "listeners") == [None]
    assert await retired_at_values(db, "scheduled_jobs") == [None]


async def test_framework_registrations_are_not_retired(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    await insert_listener(db, "__hassette__.bus", retired_at=None, source_tier="framework")

    await run_cleanup(db, retention_service)

    assert await retired_at_values(db, "listeners") == [None]


async def test_removed_app_without_a_manifest_is_still_retired(
    db: aiosqlite.Connection, retention_service: DatabaseService
) -> None:
    """Manifest writes are best-effort, so a removed app's rows must age out without one."""
    await insert_listener(db, REMOVED_APP, retired_at=None)

    await run_cleanup(db, retention_service)

    assert all(ts is not None for ts in await retired_at_values(db, "listeners"))


async def test_existing_retired_at_is_kept(db: aiosqlite.Connection, retention_service: DatabaseService) -> None:
    """Retirement re-runs every cycle; it must not push an already-retired row's age-out further out."""
    retired_at = time.time() - SECONDS_PER_DAY
    await insert_manifest(db, REMOVED_APP)
    await insert_listener(db, REMOVED_APP, retired_at=retired_at)

    await run_cleanup(db, retention_service)

    assert await retired_at_values(db, "listeners") == [retired_at]


def test_live_app_keys_counts_only_apps_with_a_running_instance(
    retention_service: DatabaseService, mock_hassette_for_db: MagicMock, tmp_path: Path
) -> None:
    """Config apps are live; beyond them, only registry keys with a running instance are."""
    configured = create_app_manifest("configured", tmp_path)
    mock_hassette_for_db.config.apps.manifests = {configured.app_key: configured}
    registry = AppRegistry()
    registry.register_app("running", 0, MagicMock())
    registry.register_app("multi", 0, MagicMock())
    registry.register_app("multi", 1, MagicMock())
    registry.record_failure("failed_only", 0, RuntimeError("boom"))
    registry.register_app("stopping", 0, MagicMock())
    registry.unregister_app("stopping")
    mock_hassette_for_db.app_handler.registry = registry

    assert retention_service.live_app_keys() == sorted([configured.app_key, "multi", "running"])


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

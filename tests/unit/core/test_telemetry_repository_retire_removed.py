"""Unit tests for TelemetryRepository retiring the registrations of apps removed from config."""

from pathlib import Path

import aiosqlite

from hassette.core.telemetry.repository import TelemetryRepository
from tests.support.factories import make_job_registration, make_listener_registration
from tests.support.helpers import create_app_manifest

from .conftest import fetch_job_field, fetch_listener_field, insert_committed_execution


async def test_retires_every_unretired_row_of_a_removed_app(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
    tmp_path: Path,
) -> None:
    """Rows are retired with or without execution history; nothing is deleted."""
    removed = create_app_manifest("removed", tmp_path)
    await telemetry_repo.upsert_app_manifest(removed)
    with_history = await telemetry_repo.register_listener(make_listener_registration(app_key=removed.app_key))
    without_history = await telemetry_repo.register_listener(
        make_listener_registration(app_key=removed.app_key, topic="topic.other", name="removed.other")
    )
    job_id = await telemetry_repo.register_job(make_job_registration(app_key=removed.app_key))
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=with_history)

    counts = await telemetry_repo.retire_removed_app_registrations([])

    assert counts == (2, 1)
    assert await fetch_listener_field(telemetry_db, with_history, "retired_at") is not None
    assert await fetch_listener_field(telemetry_db, without_history, "retired_at") is not None
    assert await fetch_job_field(telemetry_db, job_id, "retired_at") is not None


async def test_leaves_configured_apps_untouched(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection, tmp_path: Path
) -> None:
    kept = create_app_manifest("kept", tmp_path)
    await telemetry_repo.upsert_app_manifest(kept)
    listener_id = await telemetry_repo.register_listener(make_listener_registration(app_key=kept.app_key))
    job_id = await telemetry_repo.register_job(make_job_registration(app_key=kept.app_key))

    counts = await telemetry_repo.retire_removed_app_registrations([kept.app_key])

    assert counts == (0, 0)
    assert await fetch_listener_field(telemetry_db, listener_id, "retired_at") is None
    assert await fetch_job_field(telemetry_db, job_id, "retired_at") is None


async def test_leaves_registrations_without_a_manifest_untouched(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    """Framework registrations have no manifest, so an empty config never retires them."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())

    counts = await telemetry_repo.retire_removed_app_registrations([])

    assert counts == (0, 0)
    assert await fetch_listener_field(telemetry_db, listener_id, "retired_at") is None


async def test_keeps_an_existing_retired_at(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection, tmp_path: Path
) -> None:
    """Re-running on a later boot must not push an already-retired row's age-out further out."""
    removed = create_app_manifest("removed", tmp_path)
    await telemetry_repo.upsert_app_manifest(removed)
    listener_id = await telemetry_repo.register_listener(make_listener_registration(app_key=removed.app_key))
    await telemetry_db.execute("UPDATE listeners SET retired_at = 1.0 WHERE id = ?", (listener_id,))
    await telemetry_db.commit()

    counts = await telemetry_repo.retire_removed_app_registrations([])

    assert counts == (0, 0)
    assert await fetch_listener_field(telemetry_db, listener_id, "retired_at") == 1.0

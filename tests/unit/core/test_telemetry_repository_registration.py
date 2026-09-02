"""Unit tests for TelemetryRepository listener/job registration, status marking, and upsert."""

import time

import aiosqlite

from hassette.core.telemetry.repository import (
    TelemetryRepository,
)
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY
from hassette.test_utils.factories import (
    make_job_registration,
    make_listener_registration,
)

from .conftest import (
    ONCE_LISTENER_NAME,
    fetch_listener_field,
)


async def test_register_listener_inserts_and_returns_id(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_listener() inserts a row and returns a valid positive integer ID."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    assert isinstance(listener_id, int)
    assert listener_id > 0

    cursor = await telemetry_db.execute("SELECT id, app_key, topic FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == DEFAULT_TEST_APP_KEY
    assert row["topic"] == "hass.event.state_changed"


async def test_register_job_inserts_and_returns_id(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() inserts a row and returns a valid positive integer ID."""
    reg = make_job_registration()
    job_id = await telemetry_repo.register_job(reg)

    assert isinstance(job_id, int)
    assert job_id > 0

    cursor = await telemetry_db.execute("SELECT id, app_key, job_name FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == DEFAULT_TEST_APP_KEY
    assert row["job_name"] == "test_job"


async def test_register_job_persists_group(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() writes the group value to the database."""
    reg = make_job_registration(job_name="morning_job", group="morning")
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["group"] == "morning", f"Expected group='morning', got {row['group']!r}"


async def test_register_job_persists_null_group(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() persists NULL for group when group is not set."""
    reg = make_job_registration()
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["group"] is None, f"Expected group=None, got {row['group']!r}"


async def test_mark_job_removed_sets_removed_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_job_removed() sets removed_at to the current epoch time."""
    reg = make_job_registration(job_name="removable_job")
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute("SELECT removed_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is None, "removed_at should be NULL before removal"

    before_ts = time.time()
    await telemetry_repo.mark_job_removed(job_id)
    after_ts = time.time()

    cursor = await telemetry_db.execute("SELECT removed_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is not None, "removed_at should be set after mark_job_removed()"
    assert before_ts <= row["removed_at"] <= after_ts, (
        f"removed_at={row['removed_at']} should be between {before_ts} and {after_ts}"
    )


async def test_mark_job_status_updates_status_and_reason(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_job_status() writes schedule_status and schedule_status_reason to the row."""
    reg = make_job_registration(job_name="status_job")
    job_id = await telemetry_repo.register_job(reg)

    await telemetry_repo.mark_job_status(job_id, "waiting", None)

    cursor = await telemetry_db.execute(
        "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["schedule_status"] == "waiting"
    assert row["schedule_status_reason"] is None

    await telemetry_repo.mark_job_status(job_id, "completed", "trigger_error")

    cursor = await telemetry_db.execute(
        "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["schedule_status"] == "completed"
    assert row["schedule_status_reason"] == "trigger_error", (
        f"Expected schedule_status_reason='trigger_error', got {row['schedule_status_reason']!r}"
    )


async def test_mark_listener_cancelled_sets_removed_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_listener_cancelled() sets removed_at to the current epoch time."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is None, "removed_at should be NULL before removal"

    before_ts = time.time()
    await telemetry_repo.mark_listener_cancelled(listener_id)
    after_ts = time.time()

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is not None, "removed_at should be set after mark_listener_cancelled()"
    assert before_ts <= removed_at <= after_ts


async def test_register_listener_clears_removed_at_on_reregistration(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """Re-registering under the same natural key clears removed_at and preserves the row id."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    await telemetry_repo.mark_listener_cancelled(listener_id)

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is not None, "removed_at should be set after mark_listener_cancelled()"

    new_id = await telemetry_repo.register_listener(reg)
    assert new_id == listener_id, "Re-registration must preserve the row id"

    cursor = await telemetry_db.execute("SELECT removed_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is None, "removed_at should be cleared to NULL after re-registration"


async def test_upsert_same_natural_key_returns_same_id(
    telemetry_repo: TelemetryRepository,
) -> None:
    """register_listener() with same natural key returns the same ID (upsert)."""
    reg = make_listener_registration()
    id_a = await telemetry_repo.register_listener(reg)
    id_b = await telemetry_repo.register_listener(reg)
    assert id_a == id_b


async def test_upsert_different_natural_key_returns_new_id(
    telemetry_repo: TelemetryRepository,
) -> None:
    """register_listener() with different topic returns a new ID."""
    id_a = await telemetry_repo.register_listener(make_listener_registration(topic="topic.a", name="test_app.on_a"))
    id_b = await telemetry_repo.register_listener(make_listener_registration(topic="topic.b", name="test_app.on_b"))
    assert id_a != id_b


async def test_upsert_updates_mutable_fields(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """Upsert updates debounce (mutable field) on conflict."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    updated_reg = make_listener_registration(debounce=5.0)
    new_id = await telemetry_repo.register_listener(updated_reg)
    assert new_id == listener_id

    cursor = await telemetry_db.execute("SELECT debounce FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["debounce"] == 5.0


async def test_once_true_upserts_by_name_topic(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """once=True listeners with a name upsert on (name, topic) like once=False listeners."""
    # Two registrations with same name+topic — should upsert to same row
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    id_a = await telemetry_repo.register_listener(once_reg)
    id_b = await telemetry_repo.register_listener(once_reg)
    assert id_a == id_b

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE name = ?", (ONCE_LISTENER_NAME,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "Upsert should produce a single row, not two inserts"


async def test_upsert_does_not_update_human_description(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """human_description is NOT updated on upsert (not in the DO UPDATE SET list)."""
    reg = make_listener_registration(human_description="entity light.kitchen")
    listener_id = await telemetry_repo.register_listener(reg)

    reg2 = make_listener_registration(human_description="entity light.kitchen")
    new_id = await telemetry_repo.register_listener(reg2)
    assert new_id == listener_id

    cursor = await telemetry_db.execute("SELECT human_description FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["human_description"] == "entity light.kitchen"


async def test_upsert_with_name_overrides_key(
    telemetry_repo: TelemetryRepository,
) -> None:
    """Two listeners with same handler+topic but different name= get different IDs."""
    reg_a = make_listener_registration(name="listener_a")
    reg_b = make_listener_registration(name="listener_b")
    id_a = await telemetry_repo.register_listener(reg_a)
    id_b = await telemetry_repo.register_listener(reg_b)
    assert id_a != id_b

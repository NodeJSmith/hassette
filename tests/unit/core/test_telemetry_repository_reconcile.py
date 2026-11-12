"""Unit tests for TelemetryRepository reconciliation: listeners are retired, never deleted; stale jobs may be."""

import time

import aiosqlite

from hassette.core.telemetry.repository import (
    TelemetryRepository,
)
from tests.support.factories import DEFAULT_TEST_APP_KEY, make_job_registration, make_listener_registration
from tests.support.sql import insert_execution_row

from .conftest import (
    ONCE_LISTENER_NAME,
    assert_job_count,
    fetch_job_field,
    fetch_listener_field,
    insert_committed_execution,
)


async def is_retired(db: aiosqlite.Connection, listener_id: int) -> bool:
    """True when the listener row still exists and has ``retired_at`` set (fails if it was deleted)."""
    return await fetch_listener_field(db, listener_id, "retired_at") is not None


async def test_reconcile_retires_stale_listener_and_deletes_stale_job_without_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() never deletes a listener; a stale job with no history is deleted."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    assert await is_retired(telemetry_db, listener_id), "Stale listener without history should be retired"
    await assert_job_count(telemetry_db, job_id, 0, "Stale job without history should be deleted")


# dup-ignore-start: pytest test function signature — Python has no way to share a function
# signature between separate test functions (see .claude/rules/tests-unit-core.md).
async def test_reconcile_retires_stale_with_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() sets retired_at on stale rows that have execution history."""
    # dup-ignore-end
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    # Create history in the unified executions table
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=listener_id)
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="job", job_id=job_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    retired_at = await fetch_listener_field(telemetry_db, listener_id, "retired_at")
    assert retired_at is not None, "Stale listener with history should have retired_at set"

    job_retired_at = await fetch_job_field(telemetry_db, job_id, "retired_at")
    assert job_retired_at is not None, "Stale job with history should have retired_at set"


async def test_reconcile_leaves_live_listeners_unretired(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() preserves listeners whose IDs are in the live set."""
    reg_a = make_listener_registration(topic="topic.a", name="test_app.on_event_a")
    reg_b = make_listener_registration(topic="topic.b", name="test_app.on_event_b")
    id_a = await telemetry_repo.register_listener(reg_a)
    id_b = await telemetry_repo.register_listener(reg_b)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [id_a], [])

    assert not await is_retired(telemetry_db, id_a), "Live listener should be left alone"
    assert await is_retired(telemetry_db, id_b), "Stale listener should be retired"


async def test_reconcile_retires_non_live_once_listener(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() retires a non-live once=True listener like any other.

    Deleting a once=True listener that already ran is ``SessionManager.cleanup_stale_once_listeners``'s job.
    """
    live_id = await telemetry_repo.register_listener(make_listener_registration(topic="topic.live", name="live"))
    once_id = await telemetry_repo.register_listener(make_listener_registration(once=True, name=ONCE_LISTENER_NAME))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [live_id], [])

    assert await is_retired(telemetry_db, once_id), "Non-live once=True listener should be retired"
    assert not await is_retired(telemetry_db, live_id), "Live listener should be left alone"


async def test_reconcile_empty_ids_no_crash(
    telemetry_repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])


# dup-ignore-start: pytest test function signature — Python has no way to share a function
# signature between separate test functions (see .claude/rules/tests-unit-core.md).
async def test_reconcile_resets_retired_at_on_reupsert(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """After a row is retired, re-upserting it (same natural key) resets retired_at to NULL."""
    # dup-ignore-end
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    # Create history so reconciliation retires rather than deletes
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=listener_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    retired_at = await fetch_listener_field(telemetry_db, listener_id, "retired_at")
    assert retired_at is not None, "Row should be retired after reconciliation"

    new_id = await telemetry_repo.register_listener(reg)
    assert new_id == listener_id, "Re-upsert should return the same ID"

    retired_at = await fetch_listener_field(telemetry_db, listener_id, "retired_at")
    assert retired_at is None, "retired_at should be reset to NULL after re-upsert"


async def test_reconcile_deletes_stale_job_not_in_live_set(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale jobs NOT in live_job_ids when live_job_ids is non-empty."""
    job_id_a = await telemetry_repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await telemetry_repo.register_job(make_job_registration(job_name="job_b"))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [job_id_a])

    await assert_job_count(telemetry_db, job_id_a, 1, "Live job should be preserved")
    await assert_job_count(
        telemetry_db, job_id_b, 0, "Stale job without history should be deleted (non-empty live_job_ids branch)"
    )


# dup-ignore-start: pytest test function signature — Python has no way to share a function
# signature between separate test functions (see .claude/rules/tests-unit-core.md).
async def test_reconcile_retires_stale_job_with_history_non_empty_live_set(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() retires stale jobs with history when live_job_ids is non-empty."""
    # dup-ignore-end
    job_id_a = await telemetry_repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await telemetry_repo.register_job(make_job_registration(job_name="job_b"))

    await insert_execution_row(
        telemetry_db,
        kind="job",
        job_id=job_id_b,
        session_id=telemetry_session_id,
        execution_start_ts=time.time(),
        duration_ms=1.0,
    )
    await telemetry_db.commit()

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [job_id_a])

    retired_at_b = await fetch_job_field(telemetry_db, job_id_b, "retired_at")
    assert retired_at_b is not None, "Stale job with history should have retired_at set (non-empty live_job_ids branch)"

    retired_at_a = await fetch_job_field(telemetry_db, job_id_a, "retired_at")
    assert retired_at_a is None, "Live job should not be retired"


async def test_reconcile_scopes_listener_retirement_by_instance_name(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_name=...) retires only the target instance's stale listeners."""
    stale_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="instance_0", name="test_app.on_a")
    )
    stale_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="instance_1", name="test_app.on_a")
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_name="instance_0")

    assert await is_retired(telemetry_db, stale_instance_0), "Stale listener for the target instance should retire"
    assert not await is_retired(telemetry_db, stale_instance_1), "Sibling instance's listener should be untouched"


async def test_reconcile_without_instance_name_affects_all_instances(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() without instance_name is unaffected by instance boundaries.

    Matches pre-existing app_key-only-scoped behavior — every instance's stale rows are
    reconciled together.
    """
    listener_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="instance_0", name="test_app.on_a")
    )
    listener_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="instance_1", name="test_app.on_a")
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    assert await is_retired(telemetry_db, listener_instance_0), "Stale listener for instance_0 should be retired"
    assert await is_retired(telemetry_db, listener_instance_1), "Stale listener for instance_1 should be retired"


async def test_reconcile_scopes_job_deletion_by_instance_name(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_name=...) scopes scheduled_jobs deletion.

    A stale sibling-instance job (without execution history) is not deleted alongside the
    target instance — the scheduled_jobs analogue of
    test_reconcile_scopes_listener_retirement_by_instance_name.
    """
    stale_job_instance_0 = await telemetry_repo.register_job(
        make_job_registration(instance_name="instance_0", job_name="job_a")
    )
    stale_job_instance_1 = await telemetry_repo.register_job(
        make_job_registration(instance_name="instance_1", job_name="job_a")
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_name="instance_0")

    await assert_job_count(
        telemetry_db, stale_job_instance_0, 0, "Stale job for the target instance_name should be deleted"
    )
    await assert_job_count(
        telemetry_db,
        stale_job_instance_1,
        1,
        "Sibling instance's job should be unaffected by scoped reconciliation",
    )

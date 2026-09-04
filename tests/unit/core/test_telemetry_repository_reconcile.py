"""Unit tests for TelemetryRepository reconciliation of stale, live, once=True, and per-instance registrations."""

import time

import aiosqlite
import pytest

from hassette.core.telemetry.repository import (
    TelemetryRepository,
)
from tests.support.factories import DEFAULT_TEST_APP_KEY, make_job_registration, make_listener_registration
from tests.support.sql import insert_execution_row

from .conftest import (
    ONCE_LISTENER_NAME,
    assert_job_count,
    assert_listener_count,
    fetch_job_field,
    fetch_listener_field,
    insert_committed_execution,
    insert_new_session,
)


async def test_reconcile_deletes_stale_without_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale non-once listeners with no execution history."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    await assert_listener_count(telemetry_db, listener_id, 0, "Stale listener without history should be deleted")
    await assert_job_count(telemetry_db, job_id, 0, "Stale job without history should be deleted")


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
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


async def test_reconcile_preserves_live_listeners(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() preserves listeners whose IDs are in the live set."""
    reg_a = make_listener_registration(topic="topic.a", name="test_app.on_event_a")
    reg_b = make_listener_registration(topic="topic.b", name="test_app.on_event_b")
    id_a = await telemetry_repo.register_listener(reg_a)
    id_b = await telemetry_repo.register_listener(reg_b)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [id_a], [])

    await assert_listener_count(telemetry_db, id_a, 1, "Live listener should be preserved")
    await assert_listener_count(telemetry_db, id_b, 0, "Stale listener without history should be deleted")


@pytest.mark.usefixtures("telemetry_session_id")
async def test_reconcile_deletes_once_true_previous_session(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True rows from previous sessions (no current executions)."""
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=new_session_id)

    await assert_listener_count(telemetry_db, once_id, 0, "once=True listener from previous session should be deleted")


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_reconcile_preserves_once_true_with_current_executions(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() preserves once=True rows that have current-session executions."""
    # dup-ignore-end
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    # Create an execution in the CURRENT session
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=once_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=telemetry_session_id)

    await assert_listener_count(
        telemetry_db, once_id, 1, "once=True listener with current-session executions should be preserved"
    )


async def test_reconcile_empty_ids_no_crash(
    telemetry_repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
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


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
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


async def test_reconcile_once_true_delete_non_empty_live_listener_ids(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True listeners not in live IDs when live_listener_ids is non-empty."""
    live_reg = make_listener_registration(topic="topic.live", name="test_app.live")
    live_id = await telemetry_repo.register_listener(live_reg)

    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [live_id], [], session_id=new_session_id)

    await assert_listener_count(
        telemetry_db,
        once_id,
        0,
        "once=True listener from previous session should be deleted (non-empty live_listener_ids branch)",
    )

    await assert_listener_count(telemetry_db, live_id, 1, "Live listener should be preserved")


async def test_reconcile_once_true_cleanup_respects_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes the once=True cleanup block.

    Leaves a sibling instance's once=True row untouched. This is the exact regression the
    instance-scoped reconciliation feature exists to prevent — the once=True block bypasses
    the builder functions and must be scoped independently.
    """
    once_reg_0 = make_listener_registration(once=True, name=ONCE_LISTENER_NAME, instance_index=0)
    once_id_0 = await telemetry_repo.register_listener(once_reg_0)

    once_reg_1 = make_listener_registration(once=True, name=ONCE_LISTENER_NAME, instance_index=1)
    once_id_1 = await telemetry_repo.register_listener(once_reg_1)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(
        DEFAULT_TEST_APP_KEY, [], [], session_id=new_session_id, instance_index=0
    )

    await assert_listener_count(
        telemetry_db, once_id_0, 0, "once=True listener for the target instance_index should be deleted"
    )
    await assert_listener_count(
        telemetry_db, once_id_1, 1, "once=True listener for the sibling instance_index should be preserved"
    )


async def test_reconcile_scopes_listener_deletion_by_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes non-once listener deletion.

    A stale sibling-instance row (without execution history) is not deleted alongside the
    target instance.
    """
    stale_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=0)
    )
    stale_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=1)
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_index=0)

    await assert_listener_count(
        telemetry_db, stale_instance_0, 0, "Stale listener for the target instance_index should be deleted"
    )
    await assert_listener_count(
        telemetry_db, stale_instance_1, 1, "Sibling instance's listener should be unaffected by scoped reconciliation"
    )


async def test_reconcile_without_instance_index_affects_all_instances(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() without instance_index is unaffected by instance boundaries.

    Matches pre-existing app_key-only-scoped behavior — every instance's stale rows are
    reconciled together.
    """
    listener_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=0)
    )
    listener_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=1)
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    await assert_listener_count(
        telemetry_db, listener_instance_0, 0, "Stale listener for instance_index=0 should be deleted"
    )
    await assert_listener_count(
        telemetry_db, listener_instance_1, 0, "Stale listener for instance_index=1 should also be deleted"
    )


async def test_reconcile_scopes_job_deletion_by_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes scheduled_jobs deletion.

    A stale sibling-instance job (without execution history) is not deleted alongside the
    target instance — the scheduled_jobs analogue of
    test_reconcile_scopes_listener_deletion_by_instance_index.
    """
    stale_job_instance_0 = await telemetry_repo.register_job(make_job_registration(job_name="job_a", instance_index=0))
    stale_job_instance_1 = await telemetry_repo.register_job(make_job_registration(job_name="job_a", instance_index=1))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_index=0)

    await assert_job_count(
        telemetry_db, stale_job_instance_0, 0, "Stale job for the target instance_index should be deleted"
    )
    await assert_job_count(
        telemetry_db,
        stale_job_instance_1,
        1,
        "Sibling instance's job should be unaffected by scoped reconciliation",
    )

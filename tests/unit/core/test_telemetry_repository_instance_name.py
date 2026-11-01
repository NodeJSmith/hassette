"""Unit tests for TelemetryRepository rows keyed by instance name: upserts and per-instance reconciliation."""

import aiosqlite
import pytest

from hassette.core.telemetry.insert_params import stored_instance_name
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.types.types import FRAMEWORK_APP_KEY
from tests.support.factories import DEFAULT_TEST_APP_KEY, make_job_registration, make_listener_registration

from .conftest import assert_job_count, assert_listener_count, fetch_job_field, fetch_listener_field

FRAMEWORK_KEY = f"{FRAMEWORK_APP_KEY}.BusService"


async def test_listener_reorder_keeps_the_row_and_refreshes_its_index(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    """Moving a config block changes the index but not the identity, so history stays with the instance."""
    first = await telemetry_repo.register_listener(make_listener_registration(instance_name="upstairs"))
    second = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="upstairs", instance_index=3)
    )

    assert second == first
    assert await fetch_listener_field(telemetry_db, first, "instance_index") == 3


async def test_job_reorder_keeps_the_row_and_refreshes_its_index(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    first = await telemetry_repo.register_job(make_job_registration(instance_name="upstairs"))
    second = await telemetry_repo.register_job(make_job_registration(instance_name="upstairs", instance_index=3))

    assert second == first
    assert await fetch_job_field(telemetry_db, first, "instance_index") == 3


async def test_two_instances_at_one_index_do_not_share_a_row(telemetry_repo: TelemetryRepository) -> None:
    """The index no longer identifies anything: a swap mid-reload briefly holds both names at one index."""
    upstairs = await telemetry_repo.register_listener(make_listener_registration(instance_name="upstairs"))
    downstairs = await telemetry_repo.register_listener(make_listener_registration(instance_name="downstairs"))

    assert upstairs != downstairs


async def test_rename_starts_a_new_row_and_renaming_back_restores_the_old_one(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    original = await telemetry_repo.register_listener(make_listener_registration(instance_name="upstairs"))
    renamed = await telemetry_repo.register_listener(make_listener_registration(instance_name="attic"))
    await telemetry_db.execute("UPDATE listeners SET retired_at = 1.0 WHERE id = ?", (original,))
    await telemetry_db.commit()

    restored = await telemetry_repo.register_listener(make_listener_registration(instance_name="upstairs"))

    assert renamed != original
    assert restored == original
    assert await fetch_listener_field(telemetry_db, original, "retired_at") is None


async def test_framework_listener_reregistration_does_not_duplicate(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    """Without a stored name, SQLite's distinct NULLs would insert a duplicate row on every restart."""
    registration = make_listener_registration(app_key=FRAMEWORK_KEY, instance_name=None, source_tier="framework")

    first = await telemetry_repo.register_listener(registration)
    second = await telemetry_repo.register_listener(registration)

    assert second == first
    assert await fetch_listener_field(telemetry_db, first, "instance_name") == FRAMEWORK_APP_KEY


async def test_framework_job_reregistration_does_not_duplicate(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    registration = make_job_registration(app_key=FRAMEWORK_KEY, instance_name=None, source_tier="framework")

    first = await telemetry_repo.register_job(registration)
    second = await telemetry_repo.register_job(registration)

    assert second == first
    assert await fetch_job_field(telemetry_db, first, "instance_name") == FRAMEWORK_APP_KEY


async def test_app_tier_registration_without_a_name_raises(telemetry_repo: TelemetryRepository) -> None:
    with pytest.raises(ValueError, match=DEFAULT_TEST_APP_KEY):
        await telemetry_repo.register_listener(make_listener_registration(instance_name=None))
    with pytest.raises(ValueError, match=DEFAULT_TEST_APP_KEY):
        await telemetry_repo.register_job(make_job_registration(instance_name=None))


@pytest.mark.parametrize(
    ("instance_name", "source_tier", "expected"),
    [
        ("upstairs", "app", "upstairs"),
        (None, "framework", FRAMEWORK_APP_KEY),
        ("ignored", "framework", FRAMEWORK_APP_KEY),
    ],
)
def test_stored_instance_name(instance_name: str | None, source_tier, expected: str) -> None:
    assert stored_instance_name("my_app", instance_name, source_tier) == expected


@pytest.mark.parametrize("instance_name", [None, ""])
def test_stored_instance_name_refuses_an_unnamed_app(instance_name: str | None) -> None:
    with pytest.raises(ValueError, match="my_app"):
        stored_instance_name("my_app", instance_name, "app")


async def test_reconcile_scoped_to_a_name_leaves_sibling_rows_alone(
    telemetry_repo: TelemetryRepository, telemetry_db: aiosqlite.Connection
) -> None:
    """Restarting one instance must not retire or delete another's rows, wherever either sits in config."""
    stale = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="upstairs", instance_index=1, name="stale")
    )
    sibling = await telemetry_repo.register_listener(
        make_listener_registration(instance_name="downstairs", instance_index=1, name="stale")
    )
    stale_job = await telemetry_repo.register_job(make_job_registration(instance_name="upstairs", instance_index=1))
    sibling_job = await telemetry_repo.register_job(make_job_registration(instance_name="downstairs", instance_index=1))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_name="upstairs")

    await assert_listener_count(telemetry_db, stale, 0, "The reconciled instance's stale listener should be deleted")
    await assert_listener_count(telemetry_db, sibling, 1, "A sibling at the same index should be untouched")
    await assert_job_count(telemetry_db, stale_job, 0, "The reconciled instance's stale job should be deleted")
    await assert_job_count(telemetry_db, sibling_job, 1, "A sibling job at the same index should be untouched")

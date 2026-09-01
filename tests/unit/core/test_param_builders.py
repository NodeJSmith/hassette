"""Unit tests for the seed script's extracted param builder functions.

Verifies that ``execution_insert_params``, ``listener_insert_params``, and
``job_insert_params`` (all in ``hassette.core.telemetry.repository``) produce dicts whose
keys line up with the real, migrated table schema -- catching schema drift between the
param builders and the migrations at test time rather than at seed-script runtime.
"""

import sqlite3
from pathlib import Path

from seed_scenarios.base import _BLOCKING_EVENT_COLUMNS, _SESSION_COLUMNS

from hassette.core.telemetry.repository import (
    execution_insert_params,
    job_insert_params,
    listener_insert_params,
)
from hassette.test_utils.factories import (
    make_execution_record,
    make_job_registration,
    make_listener_registration,
)

# Columns present in the real schema but intentionally absent from the registration
# dataclasses / param builders -- they are post-registration lifecycle state, set
# separately by the seed script's SeedContext.add_listener/add_job (see design doc's
# Lifecycle Field Contract) and by
# TelemetryRepository.mark_job_removed/mark_listener_cancelled/reconcile_registrations.
_LIFECYCLE_ONLY_COLUMNS = {"retired_at", "removed_at"}


def _table_columns(db_path: Path, table: str) -> set[str]:
    """Return the real column names for ``table`` in the migrated database at ``db_path``."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return {row[1] for row in rows}


def test_job_insert_params_matches_register_job(_migrated_db_template: Path):  # noqa: PT019
    """job_insert_params() keys must match scheduled_jobs columns, minus id/lifecycle fields.

    register_job() (repository.py) builds its INSERT by calling job_insert_params()
    directly, so this test's real job is to guard against the param builder and the
    migrated schema drifting apart -- not to duplicate register_job's control flow.
    """
    registration = make_job_registration()
    params = job_insert_params(registration)

    expected_keys = _table_columns(_migrated_db_template, "scheduled_jobs") - {"id"} - _LIFECYCLE_ONLY_COLUMNS
    assert set(params) == expected_keys

    assert params["repeat"] == 0
    assert params["app_key"] == registration.app_key
    assert params["instance_index"] == registration.instance_index
    assert params["job_name"] == registration.job_name
    assert params["handler_method"] == registration.handler_method
    assert params["trigger_type"] == registration.trigger_type
    assert params["trigger_label"] == registration.trigger_label


def test_execution_insert_params_round_trip(_migrated_db_template: Path):  # noqa: PT019
    """execution_insert_params() keys must match executions columns; booleans coerce to int."""
    record = make_execution_record(is_di_failure=True, thread_leaked=True)
    params = execution_insert_params(record)

    expected_keys = _table_columns(_migrated_db_template, "executions") - {"id"}
    assert set(params) == expected_keys

    assert params["is_di_failure"] == 1
    assert isinstance(params["is_di_failure"], int)
    assert not isinstance(params["is_di_failure"], bool)

    assert params["thread_leaked"] == 1
    assert isinstance(params["thread_leaked"], int)
    assert not isinstance(params["thread_leaked"], bool)

    assert params["execution_id"] == record.execution_id
    assert params["session_id"] == record.session_id


def test_listener_insert_params_round_trip(_migrated_db_template: Path):  # noqa: PT019
    """listener_insert_params() keys must match listeners columns, minus id/lifecycle fields."""
    registration = make_listener_registration()
    params = listener_insert_params(registration)

    expected_keys = _table_columns(_migrated_db_template, "listeners") - {"id"} - _LIFECYCLE_ONLY_COLUMNS
    assert set(params) == expected_keys

    assert params["once"] == 0
    assert isinstance(params["once"], int)
    assert not isinstance(params["once"], bool)

    assert params["immediate"] == 0
    assert isinstance(params["immediate"], int)
    assert not isinstance(params["immediate"], bool)

    assert params["app_key"] == registration.app_key
    assert params["name"] == registration.name
    assert params["topic"] == registration.topic


def test_session_columns_match_schema(_migrated_db_template: Path):  # noqa: PT019
    """_SESSION_COLUMNS (seed_scenarios/base.py) must match the sessions table, minus id.

    sessions has no param-builder in repository.py to import (production writes go through
    a narrower path -- see design doc), so this guards the hand-typed column tuple directly
    against schema drift instead.
    """
    expected_keys = _table_columns(_migrated_db_template, "sessions") - {"id"}
    assert set(_SESSION_COLUMNS) == expected_keys


def test_blocking_event_columns_match_schema(_migrated_db_template: Path):  # noqa: PT019
    """_BLOCKING_EVENT_COLUMNS (seed_scenarios/base.py) must match the blocking_events table, minus id."""
    expected_keys = _table_columns(_migrated_db_template, "blocking_events") - {"id"}
    assert set(_BLOCKING_EVENT_COLUMNS) == expected_keys


def test_job_insert_params_repeat_always_zero():
    """job_insert_params always hardcodes repeat=0 -- ScheduledJobRegistration has no repeat field."""
    registration = make_job_registration()
    assert not hasattr(registration, "repeat")

    params = job_insert_params(registration)
    assert params["repeat"] == 0

    other = make_job_registration(job_name="another_job", trigger_type="cron", trigger_label="nightly")
    assert job_insert_params(other)["repeat"] == 0

"""Named-parameter builders and the FK-fallback INSERT helper for telemetry rows."""

import sqlite3
from logging import Logger
from typing import TYPE_CHECKING, Any

from hassette.config.classes import AppManifest
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.types.types import ExecutionStatus

if TYPE_CHECKING:
    import aiosqlite


def execution_insert_params(record: ExecutionRecord) -> dict[str, Any]:
    """Build the named-parameter dict for an executions INSERT.

    All booleans are converted to int (SQLite has no native bool type).
    Columns match the ``executions`` table schema (001.sql original; 004.sql adds ``thread_leaked``).

    Args:
        record: The unified execution record to convert.

    Returns:
        A dict of named parameters ready for ``db.execute()`` or
        ``db.executemany()``.
    """
    return {
        "kind": record.kind,
        "listener_id": record.listener_id,
        "job_id": record.job_id,
        "session_id": record.session_id,
        "execution_start_ts": record.execution_start_ts,
        "duration_ms": record.duration_ms,
        "status": record.status,
        "error_type": record.error_type,
        "error_message": record.error_message,
        "error_traceback": record.error_traceback,
        "is_di_failure": 1 if record.is_di_failure else 0,
        "source_tier": record.source_tier,
        "execution_id": record.execution_id,
        "trigger_context_id": record.trigger_context_id,
        "trigger_origin": record.trigger_origin,
        "trigger_mode": record.trigger_mode,
        "retry_count": record.retry_count,
        "attempt_number": record.attempt_number,
        "args_json": record.args_json,
        "kwargs_json": record.kwargs_json,
        "thread_leaked": 1 if record.thread_leaked else 0,
    }


# Every execution row inserts the same columns, so derive the INSERT statement once from a
# representative record's parameter keys. The batch and FK-fallback paths share this constant,
# which makes it impossible for them to build mismatched column lists.
_EXECUTION_INSERT_COLUMNS = tuple(
    execution_insert_params(
        ExecutionRecord(
            kind="handler", session_id=None, execution_start_ts=0.0, duration_ms=0.0, status=ExecutionStatus.SUCCESS
        )
    )
)

_EXECUTION_INSERT_SQL = (
    f"INSERT INTO executions ({', '.join(_EXECUTION_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join(f':{c}' for c in _EXECUTION_INSERT_COLUMNS)})"
)


def _is_fk_violation(exc: sqlite3.IntegrityError) -> bool:
    """Return True if the IntegrityError is a foreign key constraint violation.

    SQLite error messages for FK violations contain "FOREIGN KEY". Other
    IntegrityError subtypes (CHECK, NOT NULL, UNIQUE) use different messages.
    """
    return "FOREIGN KEY" in str(exc).upper()


def listener_insert_params(registration: ListenerRegistration) -> dict[str, Any]:
    """Build the named-parameter dict for a listeners INSERT.

    Args:
        registration: The listener registration data.

    Returns:
        A dict of named parameters ready for ``db.execute()``.
    """
    return {
        "app_key": registration.app_key,
        "instance_index": registration.instance_index,
        "handler_method": registration.handler_method,
        "topic": registration.topic,
        "debounce": registration.debounce,
        "throttle": registration.throttle,
        "once": 1 if registration.once else 0,
        "priority": registration.priority,
        "predicate_description": registration.predicate_description,
        "human_description": registration.human_description,
        "source_location": registration.source_location,
        "registration_source": registration.registration_source,
        "name": registration.name or "",
        "source_tier": registration.source_tier,
        "immediate": 1 if registration.immediate else 0,
        "duration": registration.duration,
        "entity_id": registration.entity_id,
        "mode": registration.mode,
        "backpressure": registration.backpressure,
    }


def job_insert_params(registration: ScheduledJobRegistration) -> dict[str, Any]:
    """Build the named-parameter dict for a scheduled_jobs INSERT.

    Args:
        registration: The scheduled job registration data.

    Returns:
        A dict of named parameters ready for ``db.execute()``.
    """
    return {
        "app_key": registration.app_key,
        "instance_index": registration.instance_index,
        "job_name": registration.job_name,
        "handler_method": registration.handler_method,
        "trigger_type": registration.trigger_type,
        "trigger_label": registration.trigger_label,
        "trigger_detail": registration.trigger_detail,
        "repeat": 0,  # repeat is always 0 for new-style jobs; triggers handle recurrence
        "args_json": registration.args_json,
        "kwargs_json": registration.kwargs_json,
        "source_location": registration.source_location,
        "registration_source": registration.registration_source,
        "source_tier": registration.source_tier,
        "group": registration.group,
        "mode": registration.mode,
        "predicate_description": registration.predicate_description,
        "human_description": registration.human_description,
        "schedule_status": registration.schedule_status,
        "schedule_status_reason": registration.schedule_status_reason,
    }


def manifest_insert_params(manifest: AppManifest) -> dict[str, Any]:
    """Build the named-parameter dict for an app_manifests UPSERT.

    Only static metadata survives to the DB -- runtime-only fields (app_config, app_dir,
    full_path, cache_key) are intentionally excluded; see the design doc's "Key Constraints"
    section for why.

    Args:
        manifest: The app manifest to convert.

    Returns:
        A dict of named parameters ready for ``db.execute()``.
    """
    # dup-ignore-start: DB-params layer output, asserted against verbatim by
    # tests/unit/core/test_manifest_repository.py. Shares field names with
    # hassette.web.mappers.manifest_response_fields() (API-response layer) by coincidence — same
    # source model, different consumer/field subset; coupling the two layers to satisfy the
    # checker would be the wrong direction.
    return {
        "app_key": manifest.app_key,
        "class_name": manifest.class_name,
        "display_name": manifest.display_name,
        "filename": manifest.filename,
        "enabled": 1 if manifest.enabled else 0,
        "autostart": 1 if manifest.autostart else 0,
        "auto_loaded": 1 if manifest.auto_loaded else 0,
    }
    # dup-ignore-end


async def _insert_row_with_fk_fallback(
    db: "aiosqlite.Connection",
    record_params: dict,
    fk_field: str,
    logger: Logger,
) -> bool:
    """Try to INSERT one row into executions; on FK violation, null the FK field and retry.

    Args:
        db: An open aiosqlite connection.
        record_params: Named-parameter dict for the initial INSERT attempt.
        fk_field: The FK column name to null on violation (``"listener_id"`` or ``"job_id"``).
        logger: Logger instance for warning/error messages.

    Returns:
        True if the row was dropped (failed even after nulling FK), False on success.
    """
    try:
        await db.execute(_EXECUTION_INSERT_SQL, record_params)
        return False
    except sqlite3.IntegrityError as exc:
        if not _is_fk_violation(exc):
            logger.error(
                "Non-FK IntegrityError on executions row (%s=%s) — dropping: %s",
                fk_field,
                record_params.get(fk_field),
                exc,
            )
            return True
        logger.warning(
            "FK violation on executions row (%s=%s) — nulling FK and retrying",
            fk_field,
            record_params.get(fk_field),
        )
        nulled_params = {**record_params, fk_field: None}
        try:
            await db.execute(_EXECUTION_INSERT_SQL, nulled_params)
            return False
        except sqlite3.IntegrityError as retry_exc:
            logger.error(
                "Failed to persist executions row even with null FK — dropping: %s",
                retry_exc,
            )
            return True

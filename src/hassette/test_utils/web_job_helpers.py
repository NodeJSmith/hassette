"""Reusable factory functions for scheduler job test data.

**Factory guide**:

- ``make_job()`` — builds a ``SimpleNamespace`` job stub with a real trigger object.
  Use for web/serialization tests that only need duck-typed attribute access.
- ``make_real_job()`` — builds a real ``ScheduledJob`` instance.
  Use for tests that exercise ``ScheduledJob.__post_init__``, ``matches()``,
  ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
"""

import re
from types import SimpleNamespace

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import After, Cron, Every, Once
from hassette.schemas.job_models import JobSummary
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY
from hassette.test_utils.web_telemetry_helpers import SYNTHETIC_TIMESTAMP
from hassette.types.enums import ExecutionMode
from hassette.types.types import SchedulerPredicate


def make_job(
    job_id: str = "job-1",
    name: str = "check_lights",
    owner_id: str = "MyApp.MyApp[0]",
    next_run: str = "2024-01-01T00:05:00",
    trigger_type: str | None = "interval",
    trigger_detail: str | None = None,
    db_id: int | None = None,
    app_key: str = "",
    instance_index: int = 0,
) -> SimpleNamespace:
    """Build a ``SimpleNamespace`` scheduler job for test fixtures.

    Uses real trigger objects (``Every``, ``Cron``, ``Once``, ``After``) that
    implement ``TriggerProtocol`` so that ``resolve_trigger()`` works via the
    ``trigger_db_type()`` path.
    """
    trigger: object
    if trigger_type == "cron":
        cron_expr = trigger_detail or "0 0 * * *"
        trigger = Cron(cron_expr)
    elif trigger_type == "interval":
        seconds = 30
        if trigger_detail is not None:
            # Parse ISO 8601 duration like "PT30S" → 30 seconds
            m = re.search(r"(\d+)S", trigger_detail)
            if m:
                seconds = int(m.group(1))
        trigger = Every(seconds=seconds)
    elif trigger_type == "once":
        trigger = Once(at=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0))
    elif trigger_type == "after":
        trigger = After(seconds=30)
    else:
        trigger = None
    return SimpleNamespace(
        job_id=job_id,
        db_id=db_id,
        name=name,
        owner_id=owner_id,
        app_key=app_key,
        instance_index=instance_index,
        next_run=next_run,
        trigger=trigger,
    )


def make_real_job(
    name: str = "test_job",
    owner_id: str = "MyApp.MyApp[0]",
    trigger: object | None = None,
    jitter: float | None = None,
    group: str | None = None,
    app_key: str = "",
    instance_index: int = 0,
    predicate: SchedulerPredicate | None = None,
    mode: ExecutionMode = ExecutionMode.SINGLE,
    db_id: int | None = None,
) -> ScheduledJob:
    """Build a real ``ScheduledJob`` instance for tests that need full object behavior.

    Use this instead of ``make_job()`` when the test exercises ``ScheduledJob.__post_init__``,
    ``matches()``, ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
    Use ``make_job()`` for web/serialization tests that only need duck-typed attribute access.

    Args:
        name: Job name. Defaults to ``"test_job"``.
        owner_id: Owner ID. Defaults to ``"MyApp.MyApp[0]"``.
        trigger: Optional trigger. Defaults to ``None``.
        jitter: Optional jitter in seconds.
        group: Optional group name.
        app_key: Optional app key.
        instance_index: Optional app instance index.
        predicate: Optional ``where=`` predicate. Does not set ``predicate_invoker`` —
            callers that need DI resolution should pass one when constructing their own job.
        mode: Execution-mode guard for the job. Defaults to ``ExecutionMode.SINGLE``.
        db_id: Database row id to stamp onto the job, as if already registered. Defaults to
            ``None`` (unregistered).
    """
    return ScheduledJob(
        owner_id=owner_id,
        next_run=date_utils.now(),
        job=lambda: None,
        name=name,
        trigger=trigger,  # pyright: ignore[reportArgumentType]
        jitter=jitter,
        group=group,
        app_key=app_key,
        instance_index=instance_index,
        predicate=predicate,
        mode=mode,
        db_id=db_id,
    )


def make_job_summary(
    job_id: int = 1,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    job_name: str = "check_lights",
    handler_method: str = "check_lights",
    trigger_type: str | None = "interval",
    trigger_label: str = "every 30s",
    trigger_detail: str | None = None,
    total_executions: int = 5,
    successful: int = 5,
    failed: int = 0,
    total_duration_ms: float | None = None,
    avg_duration_ms: float = 8.0,
    next_run: float | None = SYNTHETIC_TIMESTAMP + 3600,
    last_executed_at: float | None = SYNTHETIC_TIMESTAMP,
    last_error_type: str | None = None,
    last_error_message: str | None = None,
    group: str | None = None,
) -> JobSummary:
    """Build a JobSummary with sensible defaults."""
    effective_duration_ms = total_duration_ms if total_duration_ms is not None else total_executions * avg_duration_ms
    return JobSummary(
        job_id=job_id,
        app_key=app_key,
        instance_index=instance_index,
        job_name=job_name,
        handler_method=handler_method,
        trigger_type=trigger_type,
        trigger_label=trigger_label,
        trigger_detail=trigger_detail,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_app.py:10",
        registration_source=None,
        total_executions=total_executions,
        successful=successful,
        failed=failed,
        last_executed_at=last_executed_at,
        total_duration_ms=effective_duration_ms,
        avg_duration_ms=avg_duration_ms,
        next_run=next_run,
        last_error_type=last_error_type,
        last_error_message=last_error_message,
        group=group,
    )

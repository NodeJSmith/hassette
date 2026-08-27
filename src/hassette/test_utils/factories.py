"""Shared test factories for registration dataclasses and command objects.

Override-friendly factories that replace per-file duplicates. Every field has
a sensible default; callers pass only the fields they care about.
"""

from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock, Mock

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.commands import InvokeHandler
from hassette.conversion import STATE_REGISTRY
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor import SyncExecutor
from hassette.events.base import Event, HassContext, HassettePayload, HassPayload
from hassette.scheduler.classes import Job, ScheduleStatus
from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY, TEST_SOURCE_LOCATION
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.test_utils.recording_api import RecordingApi
from hassette.test_utils.state_proxy_mocks import configure_state_proxy_mock
from hassette.types import JobCallable, SchedulerErrorHandlerType, TriggerProtocol
from hassette.types.enums import DEFAULT_OVERLAP_MODE, ExecutionMode
from hassette.types.types import ExecutionStatus, SchedulerPredicate, SourceTier


def make_listener_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    handler_method: str = "test_app.on_event",
    topic: str = "hass.event.state_changed",
    debounce: float | None = None,
    throttle: float | None = None,
    once: bool = False,
    priority: int = 0,
    predicate_description: str | None = None,
    human_description: str | None = None,
    source_location: str = TEST_SOURCE_LOCATION,
    registration_source: str | None = None,
    name: str | None = "test_app.on_event",
    source_tier: SourceTier = "app",
    mode: ExecutionMode = DEFAULT_OVERLAP_MODE,
) -> ListenerRegistration:
    return ListenerRegistration(
        app_key=app_key,
        instance_index=instance_index,
        handler_method=handler_method,
        topic=topic,
        debounce=debounce,
        throttle=throttle,
        once=once,
        priority=priority,
        predicate_description=predicate_description,
        human_description=human_description,
        source_location=source_location,
        registration_source=registration_source,
        name=name,
        source_tier=source_tier,
        mode=mode,
    )


def make_job_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    job_name: str = "test_job",
    handler_method: str = "test_app.my_job",
    trigger_type: str = "custom",
    trigger_label: str = "once",
    trigger_detail: str | None = None,
    args_json: str = "[]",
    kwargs_json: str = "{}",
    source_location: str = TEST_SOURCE_LOCATION,
    registration_source: str | None = None,
    source_tier: SourceTier = "app",
    group: str | None = None,
    mode: ExecutionMode = DEFAULT_OVERLAP_MODE,
    predicate_description: str | None = None,
    human_description: str | None = None,
) -> ScheduledJobRegistration:
    return ScheduledJobRegistration(
        app_key=app_key,
        instance_index=instance_index,
        job_name=job_name,
        handler_method=handler_method,
        trigger_type=trigger_type,
        trigger_label=trigger_label,
        trigger_detail=trigger_detail,
        args_json=args_json,
        kwargs_json=kwargs_json,
        source_location=source_location,
        registration_source=registration_source,
        source_tier=source_tier,
        group=group,
        mode=mode,
        predicate_description=predicate_description,
        human_description=human_description,
    )


def make_execution_record(
    *,
    kind: Literal["handler", "job"] = "handler",
    session_id: int | None = 1,
    execution_start_ts: float = 0.0,
    duration_ms: float = 100.0,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    listener_id: int | None = 1,
    job_id: int | None = None,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    source_tier: SourceTier = "app",
    is_di_failure: bool = False,
    thread_leaked: bool = False,
    error_type: str | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    execution_id: str | None = "test_exec_0001",
    trigger_context_id: str | None = None,
    trigger_origin: str | None = None,
    trigger_mode: str | None = None,
    retry_count: int = 0,
    attempt_number: int = 1,
    args_json: str = "[]",
    kwargs_json: str = "{}",
) -> ExecutionRecord:
    """Build a frozen ExecutionRecord with deterministic defaults (no wall-clock reads).

    Defaults describe a single successful handler execution. Override ``kind``/``job_id``
    together to build a job execution (the DB CHECK constraint requires exactly one of
    ``listener_id``/``job_id`` to be set).
    """
    return ExecutionRecord(
        kind=kind,
        session_id=session_id,
        execution_start_ts=execution_start_ts,
        duration_ms=duration_ms,
        status=status,
        listener_id=listener_id,
        job_id=job_id,
        app_key=app_key,
        instance_index=instance_index,
        source_tier=source_tier,
        is_di_failure=is_di_failure,
        thread_leaked=thread_leaked,
        error_type=error_type,
        error_message=error_message,
        error_traceback=error_traceback,
        execution_id=execution_id,
        trigger_context_id=trigger_context_id,
        trigger_origin=trigger_origin,
        trigger_mode=trigger_mode,
        retry_count=retry_count,
        attempt_number=attempt_number,
        args_json=args_json,
        kwargs_json=kwargs_json,
    )


def make_invoke_handler_cmd(
    *,
    source_tier: SourceTier = "app",
    listener_id: int = 1,
    topic: str = "test/topic",
    listener: Any | None = None,
    event: Any | None = None,
    effective_timeout: float | None = None,
    app_level_error_handler: Any | None = None,
    is_synthetic: bool = False,
) -> MagicMock:
    """Build a MagicMock spec'd to InvokeHandler with an invocable listener."""
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = source_tier
    cmd.listener_id = listener_id
    cmd.topic = topic
    cmd.effective_timeout = effective_timeout
    cmd.app_level_error_handler = app_level_error_handler
    cmd.is_synthetic = is_synthetic

    if listener is None:
        listener = MagicMock()
        listener.invoker.invoke = AsyncMock(return_value=None)
    cmd.listener = listener

    if event is None:
        event = MagicMock()
        event.payload.event_id = "test-event-id"
        event.payload.origin = "LOCAL"
    cmd.event = event

    return cmd


def make_scheduled_job(
    *,
    job: JobCallable | None = None,
    name: str = "test_job",
    owner_id: str = "test_owner",
    next_run: ZonedDateTime | None = None,
    trigger: TriggerProtocol | None = None,
    group: str | None = None,
    jitter: float | None = None,
    timeout: float | None = None,
    timeout_disabled: bool = False,
    error_handler: SchedulerErrorHandlerType | None = None,
    mode: ExecutionMode = DEFAULT_OVERLAP_MODE,
    db_id: int | None = None,
    predicate: SchedulerPredicate | None = None,
    schedule_status: ScheduleStatus = ScheduleStatus.SCHEDULED,
) -> Job:
    """Build a real Job for testing, with sensible defaults for every field.

    ``next_run`` defaults to ``now()`` when ``schedule_status`` is ``SCHEDULED`` (the common
    case across existing tests) and to ``None`` for any other status, matching ``Job``'s own
    SCHEDULED-requires-``next_run`` invariant — pass ``schedule_status=ScheduleStatus.WAITING``/
    ``COMPLETED``/``MANUAL`` to build a non-scheduled job without also having to pass
    ``next_run=None`` explicitly.
    """
    if next_run is not None:
        resolved_next_run = next_run
    elif schedule_status is ScheduleStatus.SCHEDULED:
        resolved_next_run = date_utils.now()
    else:
        resolved_next_run = None
    return Job(
        owner_id=owner_id,
        next_run=resolved_next_run,
        schedule_status=schedule_status,
        job=job if job is not None else (lambda: None),
        name=name,
        trigger=trigger,
        group=group,
        jitter=jitter,
        timeout=timeout,
        timeout_disabled=timeout_disabled,
        error_handler=error_handler,
        mode=mode,
        db_id=db_id,
        predicate=predicate,
    )


def make_scheduler(
    *,
    wire_dequeue: bool = False,
    source_tier: SourceTier = "app",
    app_key: str = DEFAULT_TEST_APP_KEY,
    owner_id: str = "test_owner",
) -> Scheduler:
    """Create a Scheduler with mocked internals for unit testing.

    Uses a dynamic subclass per call so property overrides don't mutate the
    shared Scheduler class (safe for parallel test workers). wire_dequeue=True
    makes dequeue_job also fire _on_job_removed (needed for remove_job paths).
    """
    mock_parent = make_mock_parent(
        app_key=app_key,
        source_tier=source_tier,
        index=0,
    )

    _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806
    _TestScheduler.owner_id = property(lambda _self: owner_id)  # pyright: ignore[reportAttributeAccessIssue]
    _TestScheduler.parent = property(lambda _self: mock_parent)  # pyright: ignore[reportAttributeAccessIssue]

    scheduler = _TestScheduler.__new__(_TestScheduler)

    mock_service = Mock()
    mock_service.register_removal_callback = Mock()

    if wire_dequeue:

        def _mock_dequeue(job: Job) -> bool:
            job._dequeued = True
            scheduler._on_job_removed(job)
            return True

        mock_service.dequeue_job = Mock(side_effect=_mock_dequeue)
    else:

        def _simple_dequeue(job: Job) -> bool:
            job._dequeued = True
            return True

        mock_service.dequeue_job = Mock(side_effect=_simple_dequeue)

    async def _add_job(job: Job) -> None:
        job.mark_registered(1)

    async def _reschedule_job(job: Job, next_run: ZonedDateTime) -> None:
        job.set_next_run(next_run)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    mock_service.reschedule_job = AsyncMock(side_effect=_reschedule_job)
    mock_service.deregister_job = Mock()
    mock_service.remove_jobs = Mock(side_effect=lambda _jobs: Mock())
    mock_service.mark_job_removed = AsyncMock()

    async def _remove_job(job: Job) -> bool:
        """Mirrors the real unified removal operation at the mock boundary: sets the
        removed flag, fires _on_job_removed when wired (matching dequeue_job's mock), and
        persists removed_at via mark_job_removed when the job has a db_id — so tests that
        override mark_job_removed to track call ordering (e.g. replace-path write-ordering)
        still observe it invoked through this path.
        """
        job._dequeued = True
        if wire_dequeue:
            scheduler._on_job_removed(job)
        if job.db_id is not None:
            await mock_service.mark_job_removed(job.db_id)
        return True

    mock_service.remove_job = AsyncMock(side_effect=_remove_job)

    # Default task_bucket.spawn closes whatever coroutine it's given instead of just
    # recording the call — mark_job_removed() (an AsyncMock) produces a real coroutine
    # object when called from remove_job()'s fire-and-forget spawn, and an unconfigured
    # Mock().task_bucket.spawn(coro, ...) never runs or closes it, leaking a "coroutine
    # was never awaited" warning at some later, unrelated test's garbage collection.
    # Callers that need to inspect what was spawned still can — this only changes what
    # happens to the coroutine argument, not the mock's call-tracking.
    def _default_spawn(coro, **_kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return Mock()

    mock_service.task_bucket = Mock()
    mock_service.task_bucket.spawn = Mock(side_effect=_default_spawn)
    scheduler.scheduler_service = mock_service
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    scheduler._entity_time_subs = {}
    scheduler._error_handler = None
    scheduler._unique_name = f"test_scheduler_{app_key}"
    scheduler.logger = Mock()

    hassette_mock = MagicMock()
    hassette_mock.config.logging.scheduler_service = "INFO"
    scheduler.hassette = hassette_mock

    return scheduler


def make_mock_executor() -> MagicMock:
    """Build a MagicMock stand-in for a CommandExecutor with an awaitable execute()."""
    executor = MagicMock()
    executor.execute = AsyncMock()
    return executor


def make_mock_event() -> MagicMock:
    """Build a MagicMock spec'd to Event."""
    return MagicMock(spec=Event)


def make_recording_api(states: dict[str, Any] | None = None) -> RecordingApi:
    """Build a RecordingApi wired to a mock Hassette and a mock StateProxy.

    The mock Hassette is unsealed and carries the real STATE_REGISTRY so
    RecordingApi's state-conversion methods work as they would in production.
    The mock StateProxy exposes ``states`` (seeded from the ``states`` argument,
    or empty) and reports ``is_ready() -> True``.
    """
    hassette = make_mock_hassette(sealed=False)
    hassette.state_registry = STATE_REGISTRY

    state_proxy = AsyncMock(spec=StateProxy)
    configure_state_proxy_mock(state_proxy, states=states or {})

    return RecordingApi(hassette, state_proxy=state_proxy)


def make_hassette_event(topic: str = "hassette.ready", data: Any = None) -> Event:
    """Build an Event carrying a HassettePayload."""
    return Event(topic=topic, payload=HassettePayload(data=data))


def make_hass_event(
    event_type: str = "state_changed",
    data: Any = None,
    origin: Literal["LOCAL", "REMOTE"] = "LOCAL",
    context_id: str = "ctx-test",
) -> Event:
    """Build an Event carrying a HassPayload (Home Assistant origin)."""
    context = HassContext(id=context_id, parent_id=None, user_id=None)
    payload = HassPayload(
        event_type=event_type,
        data=data,
        origin=origin,
        time_fired=ZonedDateTime.now("UTC"),
        context=context,
    )
    return Event(topic=f"hass.{event_type}", payload=payload)


def make_mock_listener(
    *,
    error_handler: Any = None,
    listener_id: int = 1,
    db_id: int | None = None,
    owner_id: str = "test_owner",
    app_key: str = "my_app",
    instance_index: int = 1,
    topic: str = "hass.event.test",
    handler_name: str = "MyApp.on_event",
    invoke_side_effect: Any = None,
) -> MagicMock:
    """Build a MagicMock stand-in for a Listener with configurable attributes.

    Covers command-executor tests (invoke wiring), dispatch tests (db_id routing),
    and registration tests (identity fields).

    Args:
        invoke_side_effect: Applied to both ``invoke`` and ``invoker.invoke`` — the two entry
            points a caller may reach, which every failure-path test has to set in lockstep.
    """
    listener = MagicMock()
    listener.invoke = AsyncMock(side_effect=invoke_side_effect)
    listener.invoker.invoke = AsyncMock(side_effect=invoke_side_effect)
    listener.error_handler = error_handler
    listener.invoker.error_handler = error_handler
    listener.listener_id = listener_id
    listener.db_id = db_id
    listener.owner_id = owner_id
    listener.app_key = app_key
    listener.instance_index = instance_index
    listener.topic = topic
    listener.handler_name = handler_name
    listener.debounce = None
    listener.throttle = None
    listener.rate_limiter = None
    listener.once = False
    listener.priority = 0
    listener.predicate = None
    listener.duration_config = None
    return listener


def make_mock_parent(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    index: int = 0,
    unique_name: str | None = None,
    source_tier: SourceTier = "app",
    class_name: str = "TestApp",
    app_config: Any | None = None,
) -> MagicMock:
    """Build a MagicMock stand-in for an owning App resource.

    Subsumes the various local ``make_mock_parent()`` shapes across the test
    suite — this version sets all six attributes, so callers that only cared
    about a subset get harmless extras.
    """
    parent = MagicMock()
    parent.app_key = app_key
    parent.index = index
    parent.unique_name = unique_name if unique_name is not None else f"{app_key}.{index}"
    parent.source_tier = source_tier
    parent.class_name = class_name
    parent.app_config = app_config
    return parent


def make_sync_executor(*, max_workers: int = 2) -> SyncExecutor:
    """Build a standalone SyncExecutor for tests that need run_in_thread.

    ``SyncExecutor`` is a plain capability class (no Resource/Service base, no
    ``hassette``/``parent`` requirement), so this is a direct constructor call —
    no ``__new__`` bypass, no manual field wiring.  Use ``tests/unit/conftest.py:make_service``
    for tests that exercise the full ``SyncExecutorService`` lifecycle or
    config-driven max_workers.

    Caller is responsible for calling ``executor.shutdown_pool(timeout=...)`` at teardown.
    """
    executor = SyncExecutor()
    executor.rebuild_pool(max_workers=max_workers)
    return executor

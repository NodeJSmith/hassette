"""Shared test factories for registration dataclasses and command objects.

Override-friendly factories that replace per-file duplicates. Every field has
a sensible default; callers pass only the fields they care about.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.commands import InvokeHandler
from hassette.conversion import STATE_REGISTRY
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.state_proxy import StateProxy
from hassette.events.base import Event, HassContext, HassettePayload, HassPayload
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY, TEST_SOURCE_LOCATION
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.test_utils.recording_api import RecordingApi
from hassette.types import JobCallable, SchedulerErrorHandlerType, TriggerProtocol
from hassette.types.enums import DEFAULT_OVERLAP_MODE, ExecutionMode
from hassette.types.types import SchedulerPredicate, SourceTier


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
    name_auto: bool = False,
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
        name_auto=name_auto,
        mode=mode,
        predicate_description=predicate_description,
        human_description=human_description,
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
) -> ScheduledJob:
    """Build a real ScheduledJob for testing, with sensible defaults for every field."""
    return ScheduledJob(
        owner_id=owner_id,
        next_run=next_run if next_run is not None else date_utils.now(),
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
    makes dequeue_job also fire _on_job_removed (needed for cancel_job paths).
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
    mock_service.dequeue_job = Mock(side_effect=lambda job: setattr(job, "_dequeued", True) or True)

    if wire_dequeue:

        def _mock_dequeue(job: ScheduledJob) -> bool:
            job._dequeued = True
            scheduler._on_job_removed(job)
            return True

        mock_service.dequeue_job.side_effect = _mock_dequeue

    async def _add_job(job: ScheduledJob) -> None:
        job.mark_registered(1)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    scheduler.scheduler_service = mock_service
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
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
    state_proxy.states = states or {}
    state_proxy.is_ready = lambda: True

    return RecordingApi(hassette, state_proxy=state_proxy)


def make_hassette_event(topic: str = "hassette.ready", data: Any = None) -> Event:
    """Build an Event carrying a HassettePayload."""
    return Event(topic=topic, payload=HassettePayload(data=data))


def make_hass_event(
    event_type: str = "state_changed",
    data: Any = None,
    origin: str = "LOCAL",
    context_id: str = "ctx-test",
) -> Event:
    """Build an Event carrying a HassPayload (Home Assistant origin)."""
    context = HassContext(id=context_id, parent_id=None, user_id=None)
    payload = HassPayload(
        event_type=event_type,
        data=data,
        origin=origin,  # pyright: ignore[reportArgumentType]
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
) -> MagicMock:
    """Build a MagicMock stand-in for a Listener with configurable attributes.

    Covers command-executor tests (invoke wiring), dispatch tests (db_id routing),
    and registration tests (identity fields).
    """
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.invoker.invoke = AsyncMock()
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

"""Shared test factories for registration dataclasses and command objects.

Override-friendly factories that replace per-file duplicates. Every field has
a sensible default; callers pass only the fields they care about.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.commands import InvokeHandler
from hassette.conversion import STATE_REGISTRY
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.state_proxy import StateProxy
from hassette.events.base import Event, HassettePayload
from hassette.scheduler.classes import ScheduledJob
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


def make_mock_parent(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    index: int = 0,
    unique_name: str = f"{DEFAULT_TEST_APP_KEY}.0",
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
    parent.unique_name = unique_name
    parent.source_tier = source_tier
    parent.class_name = class_name
    parent.app_config = app_config
    return parent

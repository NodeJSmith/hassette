"""Shared test factories for registration dataclasses and command objects.

Override-friendly factories that replace per-file duplicates. Every field has
a sensible default; callers pass only the fields they care about.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hassette.commands import InvokeHandler
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY, TEST_SOURCE_LOCATION
from hassette.types.enums import DEFAULT_OVERLAP_MODE, ExecutionMode
from hassette.types.types import SourceTier


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

"""Raising predicates on duration-hold paths are recorded and routed like the main dispatch path.

Covers ``DurationHoldManager.hold_matches`` (reached via the duration-fire recheck) and
``DurationHoldManager.immediate_fire_task``, both wired to ``BusService.record_predicate_failure_safely``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hassette.bus.error_context import BusErrorContext
from hassette.bus.listeners import Listener
from hassette.core.bus_service import BusService
from hassette.testing import make_state_dict
from tests.support.helpers import create_listener
from tests.unit.core._fixtures_bus_scheduler import make_bus_service

ENTITY_ID = "light.kitchen"
TOPIC = f"hass.event.state_changed.{ENTITY_ID}"


def make_service_with_state() -> BusService:
    """BusService whose duration-hold manager reads an 'on' state and records via the real path."""
    svc = make_bus_service()
    svc.hassette.try_session_id.return_value = 7
    svc._executor.invoke_error_handler = AsyncMock()
    svc._duration_hold.state_reader = lambda _entity_id: make_state_dict(ENTITY_ID, "on")
    return svc


def raising_predicate(_event: object) -> bool:
    raise ValueError("predicate boom")


async def on_error(_ctx: BusErrorContext) -> None:
    pass


def make_registered_listener(db_id: int, **kwargs: object) -> Listener:
    """Listener on ``TOPIC``/``ENTITY_ID`` with a DB id, so telemetry records can be attributed."""
    listener = create_listener(topic=TOPIC, entity_id=ENTITY_ID, **kwargs)
    listener.mark_registered(db_id)
    return listener


def assert_error_recorded_and_routed(svc: BusService, listener: Listener) -> None:
    svc._executor.enqueue_record.assert_called_once()
    record = svc._executor.enqueue_record.call_args[0][0]
    assert record.kind == "handler"
    assert record.status == "error"
    assert record.error_type == "ValueError"
    assert record.error_message == "predicate boom"
    assert record.listener_id == listener.db_id
    assert record.session_id == 7

    svc._executor.invoke_error_handler.assert_awaited_once()
    handler, ctx = svc._executor.invoke_error_handler.await_args[0]
    assert handler is on_error
    assert isinstance(ctx, BusErrorContext)
    assert isinstance(ctx.exception, ValueError)
    assert ctx.topic == TOPIC
    assert ctx.execution_id == record.execution_id
    svc._executor.execute.assert_not_called()


async def test_raising_hold_predicate_on_duration_fire_is_recorded_and_routed() -> None:
    svc = make_service_with_state()
    listener = make_registered_listener(11, duration=60.0, hold_predicate=raising_predicate, error_handler=on_error)
    assert listener.duration_config is not None
    mock_timer = MagicMock()
    listener.duration_config._timer = mock_timer

    svc._duration_hold.start_duration_timer(listener, ENTITY_ID, listener.duration_config, AsyncMock())
    on_fire = mock_timer.start.call_args[0][0]
    await on_fire()
    await asyncio.sleep(0)

    assert_error_recorded_and_routed(svc, listener)


async def test_raising_predicate_on_immediate_fire_is_recorded_and_routed() -> None:
    svc = make_service_with_state()
    listener = make_registered_listener(12, immediate=True, where=raising_predicate, error_handler=on_error)

    await svc._duration_hold.immediate_fire_task(listener)
    await asyncio.sleep(0)

    assert_error_recorded_and_routed(svc, listener)


async def test_raising_predicate_on_immediate_fire_routes_to_app_level_handler() -> None:
    svc = make_service_with_state()
    listener = make_registered_listener(
        13, immediate=True, where=raising_predicate, app_error_handler_resolver=lambda: on_error
    )

    await svc._duration_hold.immediate_fire_task(listener)
    await asyncio.sleep(0)

    assert_error_recorded_and_routed(svc, listener)


async def test_synthetic_event_build_failure_is_log_only() -> None:
    """With no event to hand an error handler, a synthetic-event build failure only logs."""
    svc = make_service_with_state()

    def broken_factory(_entity_id: str, _state: object) -> object:
        raise RuntimeError("build boom")

    svc._duration_hold.make_synthetic_event = broken_factory  # pyright: ignore[reportAttributeAccessIssue]
    listener = create_listener(topic=TOPIC, entity_id=ENTITY_ID, immediate=True, error_handler=on_error)

    await svc._duration_hold.immediate_fire_task(listener)
    await asyncio.sleep(0)

    svc._executor.enqueue_record.assert_not_called()
    svc._executor.invoke_error_handler.assert_not_called()


async def test_post_predicate_failure_on_immediate_fire_is_log_only() -> None:
    """A failure after the predicate matched (here: elapsed computation) is not a predicate failure."""
    svc = make_service_with_state()

    def broken_elapsed(_state: object, _config: object) -> float:
        raise RuntimeError("elapsed boom")

    svc._duration_hold.compute_elapsed = broken_elapsed  # pyright: ignore[reportAttributeAccessIssue]
    listener = create_listener(topic=TOPIC, entity_id=ENTITY_ID, immediate=True, duration=60.0, error_handler=on_error)

    await svc._duration_hold.immediate_fire_task(listener)
    await asyncio.sleep(0)

    svc._executor.enqueue_record.assert_not_called()
    svc._executor.invoke_error_handler.assert_not_called()

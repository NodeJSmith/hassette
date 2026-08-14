"""Integration tests for error handler combinations with duration and immediate features.

Covers gaps in the test matrix:
- duration + on_error (app-level and per-listener)
- immediate + on_error (app-level and per-listener)
- immediate + duration + on_error
- on_error passthrough on the 4 Shape B delegate chains (design 007)
"""

import asyncio
import functools
from typing import TYPE_CHECKING

from whenever import ZonedDateTime

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.bus.error_context import BusErrorContext
from hassette.events import RawStateChangeEvent
from hassette.events.hassette import HassetteAppStateEvent, HassetteServiceEvent, HassetteSimpleEvent
from hassette.test_utils import make_state_dict, wait_for
from hassette.test_utils.app_harness import AppTestHarness
from hassette.test_utils.harness import HassetteHarness
from hassette.test_utils.helpers import settle

from .conftest import (
    ASYNC_SAFETY_TIMEOUT,
    DURATION,
    ELAPSED_BOUNDARY_DURATION,
    ELAPSED_EXCEEDS_OFFSET_SECONDS,
    ELAPSED_REMAINING_OFFSET_SECONDS,
    REMAINING_FIRE_TIMEOUT,
)
from .helpers import drive_state_change, send_live_event_and_wait_drain

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus
    from hassette.types.types import BusErrorHandlerType

DURATION_ERROR_TIMEOUT = DURATION + 1.0
"""Seconds to wait for an error handler behind a duration timer (duration + safety margin)."""


class ErrorCollector:
    """Records the `BusErrorContext` values an `on_error` handler receives.

    `record` takes `hassette` as a parameter rather than the collector holding it, because the
    passthrough tests at the bottom of this file construct their collector before the app exists
    and only reach a `Hassette` through `self.hassette` inside the handler.
    """

    def __init__(self) -> None:
        self.contexts: list[BusErrorContext] = []
        self.ran: asyncio.Event = asyncio.Event()

    async def record(self, hassette: "Hassette", ctx: BusErrorContext) -> None:
        self.contexts.append(ctx)
        hassette.task_bucket.post_to_loop(self.ran.set)

    def bound(self, hassette: "Hassette") -> "BusErrorHandlerType":
        """Return an `on_error` handler that records into this collector."""
        return functools.partial(self.record, hassette)

    async def wait(self, timeout: float = ASYNC_SAFETY_TIMEOUT) -> None:
        """Block until the first error is recorded."""
        await asyncio.wait_for(self.ran.wait(), timeout=timeout)

    def single(self, exc_type: type[Exception]) -> BusErrorContext:
        """Assert exactly one error of `exc_type` was recorded, and return its context."""
        assert len(self.contexts) == 1
        assert isinstance(self.contexts[0].exception, exc_type)
        return self.contexts[0]


class ErrorPassthroughConfig(AppConfig):
    """Minimal AppConfig for the on_error passthrough delegate tests below."""


def make_error_collector_pair() -> tuple[ErrorCollector, ErrorCollector]:
    """Build the (app_level, per_listener) collector pair used by the three "per-listener wins"
    tests, which prove a per-listener on_error handler takes precedence over an app-level one.
    """
    return ErrorCollector(), ErrorCollector()


async def test_duration_app_level_error_handler(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Duration timer fires, handler raises → app-level on_error receives the error context."""
    harness, hassette, bus = bus_harness

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("duration handler failed")

    # dup-ignore-start: bus.on_error(...) + bus.on_state_change(light.kitchen, changed_to="on",
    # handler=bad_handler, duration=DURATION, ...) registration — the shape shared by every
    # duration+on_error combo test in this file, differing in which collector is bound to on_error
    # (app-level here, per-listener/on_error kwarg in the sibling tests below), whether on_error=
    # is also passed per-listener, and once=. A shared helper would need to accept both the
    # collector-binding target and the optional per-listener kwarg, which is most of
    # bus.on_state_change's own signature.
    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=bad_handler,
        duration=DURATION,
        name="duration_app_level_error_handler",
    )
    # dup-ignore-end

    await drive_state_change(harness, "light.kitchen", "off", "on")

    await errors.wait(timeout=DURATION_ERROR_TIMEOUT)
    await settle()

    ctx = errors.single(ValueError)
    assert str(ctx.exception) == "duration handler failed"
    assert "bad_handler" in ctx.listener_name


async def test_duration_per_listener_error_handler_wins(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Duration fire + per-listener on_error takes precedence over app-level handler."""
    harness, hassette, bus = bus_harness

    app_level, per_listener = make_error_collector_pair()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("per-listener duration failure")

    # dup-ignore-start: same on_error+on_state_change registration shape as
    # test_duration_app_level_error_handler above, plus the per-listener on_error= kwarg this test
    # exists to prove takes precedence — see that test's note for why a shared helper isn't
    # worthwhile.
    bus.on_error(app_level.bound(hassette))
    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=bad_handler,
        duration=DURATION,
        on_error=per_listener.bound(hassette),
        name="duration_per_listener_error_handler_wins",
    )
    # dup-ignore-end

    await drive_state_change(harness, "light.kitchen", "off", "on")

    await per_listener.wait(timeout=DURATION_ERROR_TIMEOUT)
    await settle()

    per_listener.single(RuntimeError)
    assert not app_level.contexts


async def test_duration_error_handler_receives_original_event(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Error context from a duration fire carries the original triggering event."""
    harness, hassette, bus = bus_harness

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("check event in context")

    # dup-ignore-start: same on_error+on_state_change registration shape as
    # test_duration_app_level_error_handler above — this test's point is the ctx.event assertions
    # below, not the registration, so hiding it behind a helper wouldn't reduce anything meaningful.
    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=bad_handler,
        duration=DURATION,
        name="duration_error_handler_receives_original_event",
    )
    # dup-ignore-end

    await drive_state_change(harness, "light.kitchen", "off", "on")

    await errors.wait(timeout=DURATION_ERROR_TIMEOUT)
    await settle()

    ctx = errors.single(TypeError)
    assert isinstance(ctx.event, RawStateChangeEvent)
    assert ctx.event.payload.data.new_state is not None
    assert ctx.event.payload.data.new_state["state"] == "on"


async def test_duration_once_error_handler_and_removal(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """once=True + duration + on_error: handler raises, error handler fires, listener still removed."""
    harness, hassette, bus = bus_harness

    errors = ErrorCollector()
    call_count = 0

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("once + duration + error")

    # dup-ignore-start: same on_error+on_state_change registration shape as
    # test_duration_app_level_error_handler above, plus once=True — the kwarg this test exists to
    # verify still upholds the once contract despite the handler raising.
    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "light.kitchen",
        changed_to="on",
        handler=bad_handler,
        duration=DURATION,
        once=True,
        name="duration_once_error_handler_and_removal",
    )
    # dup-ignore-end

    await drive_state_change(harness, "light.kitchen", "off", "on")

    await errors.wait(timeout=DURATION_ERROR_TIMEOUT)
    await settle()
    assert call_count == 1
    errors.single(ValueError)

    await wait_for(lambda: not bus.task_bucket.pending_tasks(), desc="tasks drain")

    # Second trigger — listener should be gone (once contract upheld despite exception)
    await drive_state_change(harness, "light.kitchen", "on", "off")
    await drive_state_change(harness, "light.kitchen", "off", "on")
    await asyncio.sleep(DURATION + 0.1)

    assert call_count == 1, f"once=True handler fired {call_count} times despite error"
    assert len(errors.contexts) == 1


async def test_immediate_app_level_error_handler(bus_harness: tuple[HassetteHarness, "Hassette", "Bus"]) -> None:
    """Immediate fire handler raises → app-level on_error receives the error context."""
    harness, hassette, bus = bus_harness

    # dup-ignore-start: seed_state() + `errors = ErrorCollector()` + `async def bad_handler(...)` is
    # the standard single-collector arrange used by every test in this file that doesn't compare
    # app-level vs. per-listener precedence (those use make_error_collector_pair() instead).
    # `ErrorCollector()` alone is too trivial a call to name a helper for, and bad_handler's raised
    # exception type/message is the one thing that varies per test and is the actual point of each
    # one — the preceding seed_state() call also differs by entity, so nothing here generalizes into
    # a single shared call without losing that specificity.
    await harness.seed_state("light.kitchen", make_state_dict("light.kitchen", "on"))

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("immediate handler failed")

    # dup-ignore-end

    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "light.kitchen", handler=bad_handler, changed=False, immediate=True, name="immediate_app_level_error_handler"
    )

    await errors.wait()
    await settle()

    ctx = errors.single(ValueError)
    assert str(ctx.exception) == "immediate handler failed"
    assert "bad_handler" in ctx.listener_name


async def test_immediate_per_listener_error_handler_wins(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate fire + per-listener on_error takes precedence over app-level handler."""
    harness, hassette, bus = bus_harness

    await harness.seed_state("switch.outlet", make_state_dict("switch.outlet", "on"))

    app_level, per_listener = make_error_collector_pair()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("per-listener immediate failure")

    bus.on_error(app_level.bound(hassette))
    await bus.on_state_change(
        "switch.outlet",
        handler=bad_handler,
        changed=False,
        immediate=True,
        on_error=per_listener.bound(hassette),
        name="immediate_per_listener_error_handler_wins",
    )

    await per_listener.wait()
    await settle()

    per_listener.single(RuntimeError)
    assert not app_level.contexts


async def test_immediate_once_error_handler_and_removal(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate + once=True + on_error: handler raises, error handler fires, listener consumed."""
    harness, hassette, bus = bus_harness

    await harness.seed_state("switch.outlet", make_state_dict("switch.outlet", "on"))

    errors = ErrorCollector()
    call_count = 0

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("immediate + once + error")

    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "switch.outlet",
        handler=bad_handler,
        changed=False,
        immediate=True,
        once=True,
        name="immediate_once_error_handler_and_removal",
    )

    await errors.wait()
    await settle()
    assert call_count == 1
    errors.single(ValueError)

    # Live event — listener should be consumed
    await send_live_event_and_wait_drain(hassette, bus, "switch.outlet", "on", "off")

    assert call_count == 1, f"once=True handler fired {call_count} times despite error"


async def test_immediate_error_handler_receives_synthetic_event(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Error context from an immediate fire carries the synthetic event (old_state=None)."""
    harness, hassette, bus = bus_harness

    # dup-ignore-start: same seed_state()+single-collector arrange as
    # test_immediate_app_level_error_handler above — see that test's note for why `ErrorCollector()`
    # alone doesn't warrant a helper and bad_handler's raise stays inline.
    await harness.seed_state("sensor.temp", make_state_dict("sensor.temp", "25.5"))

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("check synthetic event in error context")

    # dup-ignore-end

    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "sensor.temp",
        handler=bad_handler,
        changed=False,
        immediate=True,
        name="immediate_error_handler_receives_synthetic_event",
    )

    await errors.wait()
    await settle()

    ctx = errors.single(TypeError)
    assert isinstance(ctx.event, RawStateChangeEvent)
    assert ctx.event.payload.data.old_state is None
    assert ctx.event.payload.data.new_state is not None
    assert ctx.event.payload.data.new_state["state"] == "25.5"


async def test_immediate_duration_elapsed_exceeds_error_handler(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate + duration (elapsed >= duration) + on_error: fires immediately, error handler called."""
    # dup-ignore-start: same seed_state()+single-collector arrange as
    # test_immediate_app_level_error_handler above — see that test's note. This occurrence differs
    # from the two prior ones in that the seed uses a computed past last_changed, not a plain state
    # value, since this three-way combo needs the elapsed-time boundary too.
    harness, hassette, bus = bus_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=ELAPSED_EXCEEDS_OFFSET_SECONDS)
    await harness.seed_state(
        "switch.boiler",
        make_state_dict("switch.boiler", "on", last_changed=past.format_iso()),
    )

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise ValueError("immediate + duration + error (elapsed exceeds)")

    # dup-ignore-end

    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "switch.boiler",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=ELAPSED_BOUNDARY_DURATION,
        name="immediate_duration_elapsed_exceeds_error_handler",
    )

    await errors.wait()
    await settle()

    ctx = errors.single(ValueError)
    assert "bad_handler" in ctx.listener_name


async def test_immediate_duration_remaining_timer_error_handler(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Immediate + duration (elapsed < duration) + on_error: timer fires after remaining, error handler called."""
    harness, hassette, bus = bus_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=ELAPSED_REMAINING_OFFSET_SECONDS)
    await harness.seed_state(
        "switch.fan",
        make_state_dict("switch.fan", "on", last_changed=past.format_iso()),
    )

    errors = ErrorCollector()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise RuntimeError("timer fire after remaining")

    bus.on_error(errors.bound(hassette))
    await bus.on_state_change(
        "switch.fan",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=ELAPSED_BOUNDARY_DURATION,
        name="immediate_duration_remaining_timer_error_handler",
    )

    await settle()
    assert not errors.contexts

    # Should fire after remaining ~2s
    await errors.wait(timeout=REMAINING_FIRE_TIMEOUT)
    await settle()

    errors.single(RuntimeError)


async def test_immediate_duration_per_listener_error_handler(
    bus_harness: tuple[HassetteHarness, "Hassette", "Bus"],
) -> None:
    """Three-way combo with per-listener on_error: per-listener wins over app-level."""
    harness, hassette, bus = bus_harness

    past = ZonedDateTime.now_in_system_tz().subtract(seconds=ELAPSED_EXCEEDS_OFFSET_SECONDS)
    await harness.seed_state(
        "switch.heater",
        make_state_dict("switch.heater", "on", last_changed=past.format_iso()),
    )

    app_level, per_listener = make_error_collector_pair()

    async def bad_handler(_event: RawStateChangeEvent) -> None:
        raise TypeError("three-way combo per-listener")

    bus.on_error(app_level.bound(hassette))
    await bus.on_state_change(
        "switch.heater",
        handler=bad_handler,
        changed=False,
        immediate=True,
        duration=ELAPSED_BOUNDARY_DURATION,
        on_error=per_listener.bound(hassette),
        name="immediate_duration_per_listener_error_handler",
    )

    await per_listener.wait()
    await settle()

    per_listener.single(TypeError)
    assert not app_level.contexts


# on_error passthrough on Shape B delegates (design 007) — each delegate forwards its on_error
# param to the true primary; these tests prove the forwarding actually reaches the error handler,
# not just that the parameter exists on the delegate's signature.


# dup-ignore-start: KI-002 (design/specs/097-dedupe-bus-test-scaffolding/known-issues.md) — decided
# to keep these 4 passthrough tests as separate functions rather than parametrize. Each varies on 3
# independent axes at once (bus registration method, handler signature, simulate() call arity), so a
# clean parametrize would need a per-case handler-builder function anyway — trading this file's direct
# "this exact primary call reaches this exact handler" readability for a marginal duplication win.
async def test_on_homeassistant_start_on_error_passthrough() -> None:
    """on_error passed to on_homeassistant_start fires via the on_call_service primary."""
    errors = ErrorCollector()

    class HaStartErrorApp(App[ErrorPassthroughConfig]):
        async def on_initialize(self) -> None:
            await self.bus.on_homeassistant_start(handler=self.on_start, name="ha_start_error", on_error=self.on_err)

        async def on_start(self) -> None:
            raise ValueError("ha start handler failed")

        async def on_err(self, ctx: BusErrorContext) -> None:
            await errors.record(self.hassette, ctx)

    async with AppTestHarness(HaStartErrorApp, config={}) as harness:
        await harness.simulate_homeassistant_start()
        await errors.wait()
        await settle()

    errors.single(ValueError)


async def test_on_hassette_service_failed_on_error_passthrough() -> None:
    """on_error passed to on_hassette_service_failed fires via the on_hassette_service_status primary."""
    errors = ErrorCollector()

    class ServiceFailedErrorApp(App[ErrorPassthroughConfig]):
        async def on_initialize(self) -> None:
            await self.bus.on_hassette_service_failed(
                handler=self.on_failed, name="service_failed_error", on_error=self.on_err
            )

        async def on_failed(self, event: HassetteServiceEvent) -> None:
            raise ValueError("service failed handler failed")

        async def on_err(self, ctx: BusErrorContext) -> None:
            await errors.record(self.hassette, ctx)

    async with AppTestHarness(ServiceFailedErrorApp, config={}) as harness:
        await harness.simulate_hassette_service_failed("SyntheticErrorPassthroughService")
        await errors.wait()
        await settle()

    errors.single(ValueError)


async def test_on_websocket_connected_on_error_passthrough() -> None:
    """on_error passed to on_websocket_connected fires via the on() primary."""
    errors = ErrorCollector()

    class WebsocketConnectedErrorApp(App[ErrorPassthroughConfig]):
        async def on_initialize(self) -> None:
            await self.bus.on_websocket_connected(
                handler=self.on_connected, name="ws_connected_error", on_error=self.on_err
            )

        async def on_connected(self, event: HassetteSimpleEvent) -> None:
            raise ValueError("websocket connected handler failed")

        async def on_err(self, ctx: BusErrorContext) -> None:
            await errors.record(self.hassette, ctx)

    async with AppTestHarness(WebsocketConnectedErrorApp, config={}) as harness:
        await harness.simulate_websocket_connected()
        await errors.wait()
        await settle()

    errors.single(ValueError)


async def test_on_app_running_on_error_passthrough() -> None:
    """on_error passed to on_app_running fires via the on_app_state_changed primary."""
    errors = ErrorCollector()

    class AppRunningErrorApp(App[ErrorPassthroughConfig]):
        async def on_initialize(self) -> None:
            await self.bus.on_app_running(handler=self.on_running, name="app_running_error", on_error=self.on_err)

        async def on_running(self, event: HassetteAppStateEvent) -> None:
            raise ValueError("app running handler failed")

        async def on_err(self, ctx: BusErrorContext) -> None:
            await errors.record(self.hassette, ctx)

    async with AppTestHarness(AppRunningErrorApp, config={}) as harness:
        await harness.simulate_app_running()
        await errors.wait()
        await settle()

    errors.single(ValueError)


# dup-ignore-end

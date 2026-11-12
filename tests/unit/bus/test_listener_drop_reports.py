"""Every listener-scoped drop site reports a near-miss to the listener's bound reporter (spec 151).

Scope vs filter (D1, D2), the filter walk (parent D5), and one reason code per cause (D5): ``filter``,
``throttled``, ``debounce_superseded``, ``once_spent``, ``busy``, ``queue_full``, ``backpressure``,
``hold_cancelled``. ``hold_recheck_failed`` and ``hold_entity_missing`` are pinned in ``test_duration_hold.py``.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from hassette_wire import BackpressurePolicy, ExecutionMode

from hassette.bus.delivery import Delivery
from hassette.bus.duration_timer import DurationTimer
from hassette.bus.listeners import MATCHED, OUT_OF_SCOPE, Listener
from hassette.bus.rate_limiter import RateLimiter
from hassette.bus.router import Router
from hassette.core.bus_service import BusService
from hassette.core.duration_hold_adapters import strip_old_state
from hassette.event_handling import predicates as P
from hassette.events import AnyEvent
from hassette.testing import create_state_change_event, wait_for
from tests.support.factories import make_hassette_event, make_mock_executor, make_mock_invoking_executor
from tests.support.helpers import async_noop, create_listener, make_controlled_clock, make_delivery, make_task_bucket
from tests.unit.core._fixtures_bus_scheduler import make_bus_service

ENTITY_ID = "light.kitchen"
TOPIC = f"hass.event.state_changed.{ENTITY_ID}"
QUIET_LOGGER = logging.getLogger("hassette.tests.drop_reports")


@dataclass
class Reports:
    """A recording ``DropReporter``."""

    calls: list[tuple[str, Any, int | None, bool]] = field(default_factory=list)

    def __call__(self, reason: Any, event: Any, *, filter_index: int | None = None, is_synthetic: bool = False):
        self.calls.append((reason, event, filter_index, is_synthetic))

    @property
    def reasons(self) -> list[str]:
        return [reason for reason, *_ in self.calls]


def bind(listener: Listener) -> Reports:
    reports = Reports()
    listener.invoker.report_drop = reports
    return reports


async def run_noop(_delivery: Delivery) -> None:
    """A rate-limiter ``run`` that does nothing."""


async def dispatch_event(
    listener: Listener, event: AnyEvent, run: Callable[[], Awaitable[None]] = async_noop, *, is_synthetic: bool = False
) -> None:
    """Dispatch ``event`` to ``listener`` through its invoker, with ``run`` standing in for the handler's run."""
    delivery = make_delivery(listener, event, is_synthetic=is_synthetic)
    await listener.invoker.dispatch(delivery, make_mock_executor(run), lambda: None)


def state_event(old: str, new: str, entity_id: str = ENTITY_ID) -> AnyEvent:
    return create_state_change_event(entity_id=entity_id, old_value=old, new_value=new)


def make_matching_service(*listeners: tuple[str, Listener]) -> BusService:
    """A ``BusService`` with only what ``_match_listeners`` touches, routing each listener on its topic."""
    service = BusService.__new__(BusService)
    service.router = Router()
    service.logger = QUIET_LOGGER
    for topic, listener in listeners:
        service.router.add_route(topic, listener)
    return service


class TestEvaluate:
    def test_scope_rejection_is_out_of_scope(self) -> None:
        base = create_listener()
        listener = Listener.create(
            topic=TOPIC,
            identity=base.identity,
            options=base.options,
            invoker=base.invoker,
            scope=[P.EntityMatches(ENTITY_ID)],
            where=P.StateTo("on"),
        )
        assert listener.evaluate(state_event("off", "on", entity_id="light.other")) == OUT_OF_SCOPE

    def test_names_the_first_rejecting_filter_and_skips_the_rest(self) -> None:
        calls: list[str] = []

        def second(_ev: object) -> bool:
            calls.append("second")
            return False

        def third(_ev: object) -> bool:
            calls.append("third")
            return True

        listener = create_listener(where=[P.StateTo("off"), P.AllOf((second, third))])
        assert listener.evaluate(state_event("off", "off")) == 1
        assert calls == ["second"], "evaluation stops at the first false filter"

    def test_nested_all_of_flattens_into_filters(self) -> None:
        listener = create_listener(where=P.AllOf((P.StateTo("on"), P.AllOf((P.StateFrom("off"),)))))
        assert len(listener.filters) == 2

    def test_any_of_is_one_filter(self) -> None:
        listener = create_listener(where=P.AnyOf((P.StateTo("on"), P.StateTo("dim"))))
        assert len(listener.filters) == 1
        assert listener.evaluate(state_event("on", "off")) == 0

    def test_match(self) -> None:
        listener = create_listener(where=P.StateTo("on"))
        assert listener.evaluate(state_event("off", "on")) == MATCHED


class TestMatchListeners:
    def test_filter_rejection_reports_the_filter_index(self) -> None:
        listener = create_listener(topic=TOPIC, where=[P.StateFrom("off"), P.StateTo("on")])
        reports = bind(listener)
        event = state_event("off", "dim")

        service = make_matching_service((TOPIC, listener))
        assert service._match_listeners([TOPIC], event) == {}

        assert reports.calls == [("filter", event, 1, False)]

    def test_scope_rejection_reports_nothing(self) -> None:
        listener = create_listener(topic=TOPIC, scope=[P.EntityMatches(ENTITY_ID)], where=P.StateTo("on"))
        reports = bind(listener)

        service = make_matching_service((TOPIC, listener))
        service._match_listeners([TOPIC], state_event("off", "on", entity_id="light.other"))

        assert reports.calls == []

    def test_user_entity_matches_in_where_counts(self) -> None:
        listener = create_listener(topic=TOPIC, where=P.EntityMatches("light.other"))
        reports = bind(listener)

        service = make_matching_service((TOPIC, listener))
        service._match_listeners([TOPIC], state_event("off", "on"))

        assert reports.reasons == ["filter"]

    def test_rejected_listener_is_not_evaluated_again_on_a_later_route(self) -> None:
        evaluations: list[object] = []

        def reject(ev: object) -> bool:
            evaluations.append(ev)
            return False

        listener = create_listener(topic=TOPIC, where=reject)
        reports = bind(listener)
        service = make_matching_service((TOPIC, listener), ("hass.event.state_changed", listener))

        service._match_listeners([TOPIC, "hass.event.state_changed"], state_event("off", "on"))

        assert len(evaluations) == 1
        assert reports.reasons == ["filter"]


class TestHandlerInvokerDrops:
    async def test_once_spent_after_a_dispatch(self) -> None:
        listener = create_listener(once=True, task_bucket=make_task_bucket())
        reports = bind(listener)
        first, second = make_hassette_event(data=1), make_hassette_event(data=2)

        await dispatch_event(listener, first)
        await dispatch_event(listener, second)

        assert reports.calls == [("once_spent", second, None, False)]

    async def test_synthetic_event_is_reported_as_synthetic(self) -> None:
        """An immediate-fire event dropped by the invoker keeps its synthetic origin (spec 147 D7)."""
        listener = create_listener(once=True, task_bucket=make_task_bucket())
        reports = bind(listener)
        spent = make_hassette_event(data=2)

        await dispatch_event(listener, make_hassette_event(data=1))
        await dispatch_event(listener, spent, is_synthetic=True)

        assert reports.calls == [("once_spent", spent, None, True)]

    async def test_cancelled_once_listener_reports_nothing(self) -> None:
        listener = create_listener(once=True, task_bucket=make_task_bucket())
        reports = bind(listener)
        listener.cancel()

        async def invoke() -> None:
            raise AssertionError("a cancelled once-listener must not run")

        await dispatch_event(listener, make_hassette_event(), invoke)

        assert reports.calls == []
        assert listener.invoker.report_drop is None

    @pytest.mark.parametrize("is_synthetic", [False, True])
    async def test_busy_single_listener(self, is_synthetic: bool) -> None:
        listener = create_listener(mode=ExecutionMode.SINGLE, task_bucket=make_task_bucket())
        reports = bind(listener)
        started, release = asyncio.Event(), asyncio.Event()

        async def hold() -> None:
            started.set()
            await release.wait()

        running = asyncio.create_task(dispatch_event(listener, make_hassette_event(data=1), hold))
        await asyncio.wait_for(started.wait(), timeout=1)

        refused = make_hassette_event(data=2)
        await dispatch_event(listener, refused, hold, is_synthetic=is_synthetic)
        release.set()
        await running

        assert reports.calls == [("busy", refused, None, is_synthetic)]

    async def test_queue_full(self) -> None:
        listener = create_listener(mode=ExecutionMode.QUEUED, task_bucket=make_task_bucket())
        reports = bind(listener)
        guard = listener.invoker.guard
        started, release = asyncio.Event(), asyncio.Event()

        async def hold() -> None:
            started.set()
            await release.wait()

        tasks = [asyncio.create_task(dispatch_event(listener, make_hassette_event(), hold))]
        await asyncio.wait_for(started.wait(), timeout=1)
        cap = guard._cap
        tasks += [asyncio.create_task(dispatch_event(listener, make_hassette_event(), hold)) for _ in range(cap)]
        await wait_for(lambda: len(guard.pending) == cap, desc="queue filled")

        overflow = make_hassette_event(data="overflow")
        await dispatch_event(listener, overflow, hold)
        release.set()
        await asyncio.gather(*tasks)

        assert reports.calls == [("queue_full", overflow, None, False)]


class TestRateLimiterDrops:
    async def test_throttled(self) -> None:
        clock = make_controlled_clock()
        limiter = RateLimiter(task_bucket=make_task_bucket(), throttle=10.0, clock=clock)
        listener = create_listener()
        reports = bind(listener)
        first, second = make_hassette_event(data=1), make_hassette_event(data=2)

        await limiter.call(make_delivery(listener, first), run_noop)
        await limiter.call(make_delivery(listener, second), run_noop)

        assert reports.calls == [("throttled", second, None, False)]

    async def test_debounce_reports_the_superseded_event_only(self) -> None:
        limiter = RateLimiter(task_bucket=make_task_bucket(), debounce=0.01)
        listener = create_listener()
        reports = bind(listener)
        ran = asyncio.Event()
        first, second = make_hassette_event(data=1), make_hassette_event(data=2)

        async def invoke(_delivery: Delivery) -> None:
            ran.set()

        await limiter.call(make_delivery(listener, first), invoke)
        await limiter.call(make_delivery(listener, second), invoke)
        await asyncio.wait_for(ran.wait(), timeout=1)

        assert reports.calls == [("debounce_superseded", first, None, False)]

    async def test_synthetic_events_are_reported_as_synthetic(self) -> None:
        """A synthetic event the limiter drops keeps its flag, including one held by a superseded debounce."""
        clock = make_controlled_clock()
        throttler = RateLimiter(task_bucket=make_task_bucket(), throttle=10.0, clock=clock)
        debouncer = RateLimiter(task_bucket=make_task_bucket(), debounce=0.01)
        listener = create_listener()
        reports = bind(listener)
        throttled, superseded = make_hassette_event(data=1), make_hassette_event(data=2)
        ran = asyncio.Event()

        async def invoke(_delivery: Delivery) -> None:
            ran.set()

        await throttler.call(make_delivery(listener), invoke)
        await throttler.call(make_delivery(listener, throttled, is_synthetic=True), invoke)
        ran.clear()
        await debouncer.call(make_delivery(listener, superseded, is_synthetic=True), invoke)
        await debouncer.call(make_delivery(listener), invoke)
        await asyncio.wait_for(ran.wait(), timeout=1)

        assert reports.calls == [("throttled", throttled, None, True), ("debounce_superseded", superseded, None, True)]

    async def test_cancel_records_nothing(self) -> None:
        limiter = RateLimiter(task_bucket=make_task_bucket(), debounce=10.0)
        listener = create_listener()
        reports = bind(listener)

        await limiter.call(make_delivery(listener), run_noop)
        limiter.cancel()

        assert reports.calls == []


class TestHoldCancelled:
    def start_timer(self) -> DurationTimer:
        timer = DurationTimer(
            task_bucket=make_task_bucket(),
            duration=60.0,
            predicates=P.StateTo("on"),
            entity_id=ENTITY_ID,
            owner_id="owner",
            create_cancel_sub=MagicMock,
            normalize_cancel_event=strip_old_state,
        )
        timer.start(async_noop)
        return timer

    async def test_an_event_that_ends_an_active_hold_says_so(self) -> None:
        assert self.start_timer().cancel_if_left_state(state_event("on", "off")) is True

    async def test_an_event_that_keeps_the_hold_says_no(self) -> None:
        timer = self.start_timer()
        assert timer.cancel_if_left_state(state_event("off", "on")) is False
        timer.cancel()

    async def test_no_active_hold_says_no(self) -> None:
        timer = self.start_timer()
        timer.cancel()
        assert timer.cancel_if_left_state(state_event("on", "off")) is False


class TestHoldCancelledThroughBusService:
    async def test_the_cancelling_event_is_reported_against_the_held_listener(self) -> None:
        """The live event that ends an active hold is a ``hold_cancelled`` near-miss of the held listener."""
        svc = make_bus_service()
        reports = Reports()
        svc._miss_recorder = MagicMock()
        svc._miss_recorder.reporter_for.return_value = reports

        svc._executor.execute = make_mock_invoking_executor().execute
        # The hold's cancel listener is built on the service's bucket; run its async handler as-is.
        svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
        listener = create_listener(
            topic=TOPIC, entity_id=ENTITY_ID, duration=60.0, where=P.StateTo("on"), hold_predicate=P.StateTo("on")
        )
        assert listener.entity_watch is not None
        await svc.add_listener(listener)

        await svc.dispatch("hass.event.state_changed", state_event("off", "on"))
        await wait_for(lambda: listener.entity_watch is not None and listener.entity_watch.timer.is_active, desc="hold")
        cancelling = state_event("on", "off")
        await svc.dispatch("hass.event.state_changed", cancelling)
        await wait_for(lambda: "hold_cancelled" in reports.reasons, desc="hold cancelled")
        listener.cancel()

        assert [call for call in reports.calls if call[0] == "hold_cancelled"] == [
            ("hold_cancelled", cancelling, None, False)
        ]


class TestBackpressure:
    async def test_drop_newest_reports_backpressure(self) -> None:
        listener = create_listener(topic=TOPIC, backpressure=BackpressurePolicy.DROP_NEWEST)
        reports = bind(listener)
        service = BusService.__new__(BusService)
        service.logger = QUIET_LOGGER
        service._dispatch_semaphore = asyncio.Semaphore(0)
        service._last_saturation_warn_ts = time.monotonic()  # inside the warning window: no config read
        event = state_event("off", "on")

        await service._spawn_dispatch_task(make_delivery(listener, event))

        assert reports.calls == [("backpressure", event, None, False)]

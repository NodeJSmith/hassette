"""Timing of one event's listener-matching pass when a listener's ``where`` rejects it.

The case: an app listener on ``light.kitchen`` with ``changed_to="on"``, and an event for that entity
turning off. The event is in the listener's scope, so the ``where`` filter is what rejects it — the path
that records a near-miss. Compare runs of this file across commits to see what recording adds.
"""

import logging
from functools import partial
from unittest.mock import MagicMock

from pytest_benchmark.fixture import BenchmarkFixture

from hassette.bus.router import Router
from hassette.core.bus_service import BusService
from hassette.core.listener_miss_recorder import ListenerMissRecorder
from hassette.event_handling import predicates as P
from hassette.testing import create_state_change_event
from tests.support.helpers import create_listener

ENTITY_ID = "light.kitchen"
LISTENER_DB_ID = 1
ROUNDS = 20_000
"""Timed rounds; one matching pass takes about a tenth of a millisecond, so many rounds keep the mean stable."""

QUIET_LOGGER = logging.getLogger("hassette.benchmarks.listener_matching")
QUIET_LOGGER.setLevel(logging.WARNING)


def make_bus_service(*, recording: bool = False) -> BusService:
    """Build a ``BusService`` holding one rejecting app listener, without a ``Hassette`` instance.

    Bypasses ``Resource.__init__`` and installs only what ``_match_listeners`` touches. With ``recording``,
    the listener reports its drops to a real ``ListenerMissRecorder``, bound the way ``BusService`` binds it.
    """
    listener = create_listener(
        topic=f"hass.event.state_changed.{ENTITY_ID}",
        where=[P.EntityMatches(ENTITY_ID), P.StateTo("on")],
        app_key="bench_app",
        name="bench_listener",
        logger=QUIET_LOGGER,
    )
    listener.mark_registered(LISTENER_DB_ID)
    if recording:
        listener.invoker.report_drop = partial(ListenerMissRecorder(MagicMock()).record, listener)
    service = BusService.__new__(BusService)
    service.router = Router()
    service.router.add_route(listener.topic, listener)
    service.logger = QUIET_LOGGER
    return service


def test_match_rejected_by_where(benchmark: BenchmarkFixture) -> None:
    """Match one in-scope event that the listener's ``changed_to`` filter rejects, with no reporter bound."""
    run_rejected_match(benchmark, make_bus_service())


def test_match_rejected_by_where_recording(benchmark: BenchmarkFixture) -> None:
    """The same pass with the drop recorded in memory, as for a registered app listener with a database."""
    run_rejected_match(benchmark, make_bus_service(recording=True))


def run_rejected_match(benchmark: BenchmarkFixture, service: BusService) -> None:
    event = create_state_change_event(entity_id=ENTITY_ID, old_value="on", new_value="off")
    routes = service.expand_topics("hass.event.state_changed", event)

    def match() -> None:
        assert not service._match_listeners(routes, event)

    benchmark.pedantic(match, rounds=ROUNDS, iterations=1)

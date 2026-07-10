"""Contract tests for Bus synchronous registration.

These tests verify the core architectural contract: registration is synchronous —
db_id is set and the listener is routable before on_state_change() / on() returns.

Tests:
- sub.listener.db_id is a valid integer immediately after on() returns
- Listener is routable only after DB registration completes (db_id set before route insertion)
- Router methods are synchronous plain def (no async, no FairAsyncRLock)
- DB failure propagates out of on() — fails app startup rather than degrading silently
"""

import importlib.util
import inspect
import pathlib
import typing
from unittest.mock import AsyncMock, patch

import pytest

from hassette.bus.router import Router
from hassette.events.base import Event

if typing.TYPE_CHECKING:
    from hassette.bus import Bus
    from hassette.core.bus_service import BusService
    from hassette.test_utils.harness import HassetteHarness


async def handler_contract(event) -> None:
    pass


@pytest.fixture
async def contract_harness(
    hassette_harness,
    test_config,
) -> "typing.AsyncIterator[HassetteHarness]":
    """Function-scoped harness for contract tests."""
    harness = hassette_harness(test_config)
    harness.with_bus()
    await harness.start()
    try:
        yield harness
    finally:
        await harness.stop()


@pytest.fixture
def bus(contract_harness: "HassetteHarness") -> "Bus":
    """The Bus from the contract harness."""
    return contract_harness.bus


@pytest.fixture
def bus_service(contract_harness: "HassetteHarness") -> "BusService":
    """The BusService from the contract harness."""
    return contract_harness.bus_service


async def test_db_id_set_immediately_after_on_returns(
    bus: "Bus",
) -> None:
    """sub.listener.db_id is a valid integer immediately after on() returns.

    Under synchronous registration, the DB INSERT is awaited inline before
    returning to the caller. No background task, no deferred future to await.
    """
    sub = await bus.on(topic="test.contract.immediate_db_id", handler=handler_contract, name="immediate_test")

    assert sub.listener.db_id is not None, "db_id must be set immediately on return"
    assert isinstance(sub.listener.db_id, int), f"db_id must be int, got {type(sub.listener.db_id)}"
    assert sub.listener.db_id > 0, f"db_id must be a positive integer, got {sub.listener.db_id}"


async def test_listener_routable_after_registration(
    bus: "Bus",
) -> None:
    """Listener is in routing table and has a db_id immediately after on() returns.

    Under synchronous registration, both db_id assignment and route insertion
    happen inside add_listener() before returning. The listener must be fully
    ready (routable + persisted) by the time on() returns to the caller.
    """
    received: list[Event] = []

    async def capturing_handler(event: Event) -> None:
        received.append(event)

    sub = await bus.on(topic="test.contract.routable", handler=capturing_handler, name="routable_test")

    # Both conditions hold immediately — no await needed
    listeners = bus.get_listeners()
    assert len(listeners) == 1, "Handler must be in routing table immediately"
    assert sub.listener.db_id is not None, "db_id must be set immediately"
    assert sub.listener.db_id > 0, "db_id must be positive"


async def test_subscription_has_no_registration_task(
    bus: "Bus",
) -> None:
    """Subscription has no registration_task field.

    The registration_task completion signal is removed. db_id is the only
    identifier and is set synchronously before on() returns.
    """
    sub = await bus.on(topic="test.contract.no_task", handler=handler_contract, name="no_task_test")

    assert not hasattr(sub, "registration_task"), "Subscription must not have registration_task field"


async def test_db_failure_propagates_out_of_on(
    bus: "Bus",
    bus_service: "BusService",
) -> None:
    """DB failure propagates out of on() — no silent degradation.

    Under synchronous registration, registration errors propagate out of
    on_initialize() and mark the app FAILED.
    """
    with (
        patch.object(bus_service._executor, "register_listener", new=AsyncMock(side_effect=RuntimeError("DB down"))),
        pytest.raises(RuntimeError, match="DB down"),
    ):
        await bus.on(topic="test.contract.db_failure", handler=handler_contract, name="db_fail_test")

    # No listeners should be routable after a failure
    listeners = bus.get_listeners()
    assert len(listeners) == 0, "No listener must be routable when DB registration fails"


class TestRouterSyncContract:
    """Router mutation and query methods are plain def, not coroutines.

    These tests prevent silent regression where someone re-adds async to Router
    methods. Checking at the class level catches both instance and unbound forms.
    """

    ROUTER_MUTATION_METHODS: typing.ClassVar[list[str]] = [
        "add_route",
        "remove_route",
        "remove_listener_by_id",
        "clear_owner",
    ]

    ROUTER_QUERY_METHODS: typing.ClassVar[list[str]] = [
        "get_topic_listeners",
        "get_listeners_by_owner",
    ]

    def test_all_router_methods_are_plain_def(self) -> None:
        """All 6 Router mutation and query methods are plain def, not async def."""
        router = Router()
        all_method_names = self.ROUTER_MUTATION_METHODS + self.ROUTER_QUERY_METHODS

        for name in all_method_names:
            method = getattr(router, name)
            assert not inspect.iscoroutinefunction(method), (
                f"Router.{name} must be a plain def, not async def. "
                "Async Router methods reintroduce deferred routing and ordering bugs."
            )

    def test_router_has_no_lock_attribute(self) -> None:
        """Router instance has no lock attribute."""
        router = Router()
        assert not hasattr(router, "lock"), (
            "Router must not have a lock attribute. "
            "The synchronous routing design relies on asyncio cooperative scheduling, not locking."
        )

    def test_router_source_has_no_fair_async_rlock(self) -> None:
        """router.py does not import or use FairAsyncRLock."""
        spec = importlib.util.find_spec("hassette.bus.router")
        assert spec is not None
        assert spec.origin is not None
        source = pathlib.Path(spec.origin).read_text()

        assert "FairAsyncRLock" not in source, (
            "router.py must not reference FairAsyncRLock. The synchronous routing design does not use async primitives."
        )

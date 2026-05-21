"""Contract tests for Bus routing vs DB registration independence.

These tests verify the core architectural contract introduced by the sync-routing
redesign: routing (event delivery) and database registration (telemetry persistence)
are independent operations. A DB failure must not prevent event delivery, and the
registration_task completion signal must resolve regardless of outcome.

Tests:
- AC#2: DB failure doesn't affect routing — handler is invoked with db_id=None
- AC#5: Router methods are synchronous plain def (no async, no FairAsyncRLock)
- AC#6: registration_task resolves with None even when DB registration fails
"""

import asyncio
import importlib.util
import inspect
import pathlib
import typing
from unittest.mock import AsyncMock, patch

import pytest

from hassette.bus.router import Router
from hassette.events.base import Event


class _CustomDbError(Exception):
    pass


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


async def test_db_failure_does_not_prevent_event_delivery(
    bus: "Bus",
    bus_service: "BusService",
    contract_harness: "HassetteHarness",
) -> None:
    """AC#2: A handler receives events even when its database registration fails.

    The routing contract: route insertion is synchronous and unconditional. DB
    registration is a fire-and-forget background task whose failure must not affect
    whether the handler is present in the routing table or receives dispatched events.
    """
    received: list[Event] = []
    handler_called = asyncio.Event()

    async def capturing_handler(event: Event) -> None:
        received.append(event)
        contract_harness.hassette.task_bucket.post_to_loop(handler_called.set)

    # Patch _executor.register_listener to raise — simulates DB write failure.
    # Keep the patch active while awaiting registration_task: the background DB task
    # runs after bus.on() returns, so the patch must stay in effect until the task finishes.
    with patch.object(bus_service._executor, "register_listener", new=AsyncMock(side_effect=RuntimeError("DB down"))):
        sub = bus.on(topic="test.contract.db_failure", handler=capturing_handler)

        # Handler must be immediately routable despite the pending DB failure
        listeners = bus.get_listeners()
        assert len(listeners) == 1, "Handler must be present in routing table even with DB failure"
        assert listeners[0].listener_id == sub.listener.listener_id

        # Wait for registration_task to settle so DB error has been processed
        if sub.registration_task is not None:
            await sub.registration_task

        # DB registration failed → db_id must be None
        assert sub.listener.db_id is None, "db_id must be None when DB registration failed"

    # Now dispatch an event and confirm the handler fires
    event = Event(topic="test.contract.db_failure", payload=None)
    await contract_harness.hassette.send_event("test.contract.db_failure", event)

    await asyncio.wait_for(handler_called.wait(), timeout=3.0)

    assert len(received) == 1, "Handler must be invoked despite DB failure"


async def test_db_failure_handler_still_in_routing_table(
    bus: "Bus",
    bus_service: "BusService",
) -> None:
    """AC#2 supplement: After DB failure, the handler remains in get_listeners().

    This confirms routing independence: DB failure does not trigger route removal.
    """
    # Keep patch active while awaiting — background task runs after bus.on() returns
    with patch.object(bus_service._executor, "register_listener", new=AsyncMock(side_effect=Exception("DB error"))):
        sub = bus.on(topic="test.contract.still_routed", handler=handler_contract)

        # Settle the registration_task so the exception has been caught and swallowed
        if sub.registration_task is not None:
            await sub.registration_task

    # Route must still be present after DB failure
    listeners = bus.get_listeners()
    assert len(listeners) == 1
    assert listeners[0].listener_id == sub.listener.listener_id
    assert sub.listener.db_id is None


async def test_registration_task_resolves_on_db_failure(
    bus: "Bus",
    bus_service: "BusService",
) -> None:
    """AC#6: Awaiting registration_task after a DB failure resolves with None (no exception).

    registration_task is a completion signal, not a success signal. It must resolve
    regardless of whether the DB write succeeded or failed. This allows callers to
    use it as a barrier without needing exception handling.

    The patch must remain active while awaiting registration_task — the background
    DB task runs after bus.on() returns, so exiting the context manager before the
    task completes would allow the real stub to run and set db_id.
    """
    with patch.object(bus_service._executor, "register_listener", new=AsyncMock(side_effect=RuntimeError("DB down"))):
        sub = bus.on(topic="test.contract.task_resolves", handler=handler_contract)

        assert sub.registration_task is not None, "registration_task must be set"

        # Must resolve without raising — catching any exception here would indicate a bug
        result = await sub.registration_task
        assert result is None, f"registration_task must resolve with None, got {result!r}"

        # Confirm DB persistence did not succeed
        assert sub.listener.db_id is None


async def test_registration_task_resolves_on_exception_subclass(
    bus: "Bus",
    bus_service: "BusService",
) -> None:
    """AC#6 variant: registration_task resolves when the executor raises a non-RuntimeError.

    The patch must remain active while awaiting registration_task — the background DB
    task runs after bus.on() returns, so the patch must stay in effect until the task
    completes.
    """

    with patch.object(bus_service._executor, "register_listener", new=AsyncMock(side_effect=_CustomDbError("custom"))):
        sub = bus.on(topic="test.contract.custom_exc", handler=handler_contract)

        assert sub.registration_task is not None
        result = await sub.registration_task
        assert result is None
        assert sub.listener.db_id is None


async def test_registration_task_resolves_on_success(
    bus: "Bus",
) -> None:
    """AC#6 baseline: registration_task resolves with None when DB registration succeeds."""
    sub = bus.on(topic="test.contract.task_success", handler=handler_contract)

    assert sub.registration_task is not None
    result = await sub.registration_task
    assert result is None
    # On success, db_id must be set (the harness stub returns a sequential int)
    assert sub.listener.db_id is not None, "db_id must be set after successful registration"


class TestRouterSyncContract:
    """AC#5: Router mutation and query methods are plain def, not coroutines.

    These tests prevent silent regression where someone re-adds async to Router
    methods. Checking at the class level catches both instance and unbound forms.
    """

    ROUTER_MUTATION_METHODS: typing.ClassVar[list[str]] = [
        "add_route",
        "remove_route",
        "remove_listener",
        "remove_listener_by_id",
        "clear_owner",
    ]

    ROUTER_QUERY_METHODS: typing.ClassVar[list[str]] = [
        "get_topic_listeners",
        "get_listeners_by_owner",
    ]

    def test_all_router_methods_are_plain_def(self) -> None:
        """AC#5: All 7 Router mutation and query methods are plain def, not async def.

        A coroutine function returns a coroutine object instead of executing immediately.
        Any Router method that is async would reintroduce deferred routing and break
        the synchronous ordering guarantee.
        """
        router = Router()
        all_method_names = self.ROUTER_MUTATION_METHODS + self.ROUTER_QUERY_METHODS

        for name in all_method_names:
            method = getattr(router, name)
            assert not inspect.iscoroutinefunction(method), (
                f"Router.{name} must be a plain def, not async def. "
                "Async Router methods reintroduce deferred routing and ordering bugs."
            )

    def test_router_mutation_methods_are_plain_def(self) -> None:
        """AC#5: Router mutation methods (add_route, remove_*, clear_owner) are plain def."""
        router = Router()
        for name in self.ROUTER_MUTATION_METHODS:
            method = getattr(router, name)
            assert not inspect.iscoroutinefunction(method), f"Router.{name} must be plain def (mutation method)"

    def test_router_query_methods_are_plain_def(self) -> None:
        """AC#5: Router query methods (get_topic_listeners, get_listeners_by_owner) are plain def."""
        router = Router()
        for name in self.ROUTER_QUERY_METHODS:
            method = getattr(router, name)
            assert not inspect.iscoroutinefunction(method), f"Router.{name} must be plain def (query method)"

    def test_router_has_no_lock_attribute(self) -> None:
        """AC#5: Router instance has no lock attribute.

        The previous design used FairAsyncRLock. Removing the lock is intentional —
        asyncio's cooperative scheduler guarantees that code between await points runs
        atomically, and all Router methods have no await points.
        """
        router = Router()
        assert not hasattr(router, "lock"), (
            "Router must not have a lock attribute. "
            "The synchronous routing design relies on asyncio cooperative scheduling, not locking."
        )

    def test_router_source_has_no_fair_async_rlock(self) -> None:
        """AC#5: router.py does not import or use FairAsyncRLock.

        Verifies the source-level constraint, not just the runtime instance. This
        catches cases where FairAsyncRLock is imported but unused (lint dead code).
        """
        spec = importlib.util.find_spec("hassette.bus.router")
        assert spec is not None
        assert spec.origin is not None
        source = pathlib.Path(spec.origin).read_text()

        assert "FairAsyncRLock" not in source, (
            "router.py must not reference FairAsyncRLock. The synchronous routing design does not use async primitives."
        )

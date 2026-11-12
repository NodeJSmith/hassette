"""Tests for ``Delivery.invoke()`` effective timeout resolution at the BusService level."""

from unittest.mock import MagicMock

from hassette.bus.delivery import Delivery
from hassette.bus.listeners import Listener
from hassette.commands import InvokeHandler
from hassette.testing.config import TEST_CONFIG_TIMEOUT_SECONDS
from tests.support.factories import make_mock_event, make_mock_executor
from tests.support.helpers import create_listener

from .conftest import make_bus_service


async def dispatch_and_get_cmd(
    listener: Listener, *, event: MagicMock | None = None, executor: MagicMock | None = None
) -> InvokeHandler:
    """Invoke a delivery to ``listener`` the way BusService dispatch does, returning the InvokeHandler.

    Shared by the BusService dispatch test files (timeout, error_handler), matching
    ``run_job_and_get_cmd`` in test_scheduler_service_timeout.py for the scheduler_service family.
    Kept local to this file rather than promoted to tests/support/ or conftest.py, which is shared
    write-target scope across unrelated test groups (see design/specs/098-dedup-core-service-tests/design.md).
    Callers that fire more than once against one executor pass their own; the returned command is
    always the most recent ``execute`` call.
    """
    event = event if event is not None else make_mock_event()
    executor = executor if executor is not None else make_mock_executor()

    # dup-ignore-start: BusService-level fire-and-extract-cmd tail mirrors invoke_and_get_cmd in
    # tests/unit/bus/test_delivery.py — same Delivery.invoke behavior verified at two
    # integration points (Bus vs BusService) by design, not copy-paste.
    await Delivery(listener, event, "test.topic").invoke(executor, lambda: TEST_CONFIG_TIMEOUT_SECONDS)

    cmd = executor.execute.call_args[0][0]
    assert isinstance(cmd, InvokeHandler)
    # dup-ignore-end
    return cmd


class TestDispatchResolvesEffectiveTimeout:
    async def test_dispatch_resolves_effective_timeout_from_listener(self) -> None:
        """listener.timeout=5 -> effective_timeout=5."""
        listener = create_listener(topic="test.topic", timeout=5.0)

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.effective_timeout == 5.0

    async def test_dispatch_resolves_effective_timeout_from_config(self) -> None:
        """listener.timeout=None -> uses config default."""
        listener = create_listener(topic="test.topic")

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.effective_timeout == TEST_CONFIG_TIMEOUT_SECONDS

    async def test_dispatch_resolves_timeout_disabled(self) -> None:
        """listener.timeout_disabled=True -> effective_timeout=None."""
        listener = create_listener(topic="test.topic", timeout_disabled=True)

        cmd = await dispatch_and_get_cmd(listener)

        assert cmd.effective_timeout is None

    async def test_once_listener_removed_after_dispatch(self) -> None:
        """once=True handler is removed from the bus after dispatch regardless of execution outcome."""
        svc = make_bus_service(config_timeout=TEST_CONFIG_TIMEOUT_SECONDS)
        listener = create_listener(topic="test.topic", timeout=0.001, once=True)
        event = make_mock_event()

        # After dispatch, listener.once should cause removal
        # We test that _dispatch calls remove_listener after once handler fires
        svc.remove_listener = MagicMock(return_value=None)

        await svc._dispatch(Delivery(listener, event, "test.topic"))

        # Verify remove_listener was called for the once listener
        svc.remove_listener.assert_called_once_with(listener)

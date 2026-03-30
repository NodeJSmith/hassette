"""Shutdown system tests — verify clean shutdown against a live Home Assistant container.

These tests verify that Hassette's shutdown path completes cleanly with all
children in terminal state and event streams closed. They exercise the full
Hassette.shutdown() override (total timeout + _finalize_shutdown propagation +
_on_children_stopped hook + close_streams fallback).

Run with:
    pytest -m system -v
"""

import pytest

from hassette.resources.base import Service
from hassette.test_utils import make_service_failed_event, wait_for
from hassette.types.enums import ResourceStatus
from tests.system.conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system, pytest.mark.filterwarnings("default::DeprecationWarning")]


async def test_shutdown_completes_cleanly(ha_container, tmp_path):
    """Hassette.shutdown() terminates all children and closes event streams."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        # Verify we're fully running before shutdown
        assert hassette.session_id > 0
        assert len(hassette.children) > 0

    # After the context manager exits, shutdown has completed
    assert hassette._shutdown_completed is True
    assert hassette.status == ResourceStatus.STOPPED
    assert hassette.event_streams_closed


async def test_all_children_stopped_after_shutdown(ha_container, tmp_path):
    """Every direct child of Hassette is in STOPPED state after shutdown."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        children_snapshot = list(hassette.children)

    for child in children_snapshot:
        assert child._shutdown_completed is True, (
            f"{child.unique_name} should be _shutdown_completed after Hassette shutdown"
        )
        assert child.status == ResourceStatus.STOPPED, f"{child.unique_name} should be STOPPED, got {child.status}"


async def test_grandchildren_stopped_after_shutdown(ha_container, tmp_path):
    """Grandchildren (e.g., StateProxy.Bus, AppHandler.AppLifecycleService) are also STOPPED."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        all_descendants = [
            (grandchild.unique_name, grandchild) for child in hassette.children for grandchild in child.children
        ]

    for name, desc in all_descendants:
        assert desc._shutdown_completed is True, f"Grandchild {name} should be _shutdown_completed"
        assert desc.status == ResourceStatus.STOPPED, f"Grandchild {name} should be STOPPED, got {desc.status}"


class _AlwaysFailingService(Service):
    """Service whose on_initialize always raises — triggers the restart cascade."""

    async def serve(self) -> None:
        pass

    async def on_initialize(self) -> None:
        raise RuntimeError("always fails")


async def test_bus_driven_failed_cascade_triggers_shutdown(ha_container, tmp_path):
    """Full bus-driven cascade: FAILED event → restart → fail → repeat → shutdown.

    Uses a real Hassette with a real ServiceWatcher and BusService. Verifies that
    the watcher's bus listeners correctly wire up: a single FAILED event triggers
    restart_service, which fails, emits another FAILED event, exhausts the retry
    budget, and calls hassette.shutdown().

    Moved from integration tests because the cascade requires a fully-wired Hassette
    with clean bus state — module-scoped integration fixtures pollute the BusService
    router between tests.
    """
    config = make_system_config(ha_container, tmp_path)
    config.service_restart_max_attempts = 2
    config.service_restart_backoff_seconds = 0.0

    async with startup_context(config) as hassette:
        # Add a service that always fails on initialize
        dummy = _AlwaysFailingService(hassette)
        hassette.children.append(dummy)

        event = make_service_failed_event(dummy)

        # Stub hassette.shutdown() to just set the event. We can't let the real
        # shutdown run here — it would tear down the Hassette while startup_context
        # still owns the lifecycle. startup_context.__aexit__ handles the real
        # shutdown via shutdown_event.set() → run_forever exits → clean teardown.
        original_shutdown = hassette.shutdown

        async def _shutdown_stub() -> None:
            hassette.shutdown_event.set()

        hassette.shutdown = _shutdown_stub  # pyright: ignore[reportAttributeAccessIssue]

        try:
            # Fire the FAILED event — the ServiceWatcher's bus listener should catch it
            # and start the restart cascade:
            #   FAILED → restart_service (attempt 1) → on_initialize raises
            #   → handle_failed emits FAILED → restart_service (attempt 2 ≥ max)
            #   → hassette.shutdown()  (stub sets shutdown_event)
            await hassette.send_event(event.topic, event)

            await wait_for(
                lambda: hassette.shutdown_event.is_set(),
                timeout=10.0,
                desc="shutdown triggered after max restart attempts exceeded",
            )
        finally:
            # Restore real shutdown so startup_context can clean up properly
            hassette.shutdown = original_shutdown  # pyright: ignore[reportAttributeAccessIssue]

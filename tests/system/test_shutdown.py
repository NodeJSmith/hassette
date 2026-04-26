"""System tests for Hassette shutdown lifecycle."""

import asyncio
import sqlite3

import pytest

from hassette.resources.base import Service
from hassette.test_utils import make_service_failed_event, wait_for
from hassette.types.enums import ResourceStatus

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]


async def test_clean_shutdown(ha_container: str, tmp_path):
    """After startup_context exits, Hassette is fully shut down and the session row is finalized."""
    config = make_system_config(ha_container, tmp_path)

    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        db_path = hassette.config.db_path or (hassette.config.data_dir / "hassette.db")

    # After the context exits, assert shutdown completed
    assert hassette._shutdown_completed is True
    assert hassette.status == ResourceStatus.STOPPED
    assert hassette.event_streams_closed is True

    for child in hassette.children:
        assert child.status == ResourceStatus.STOPPED, f"Child {child.unique_name} expected STOPPED, got {child.status}"

    # Verify session row finalized via a fresh sqlite3 connection
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT status, stopped_at FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is not None, "Session row not found"
    status, stopped_at = row
    assert status == "success", f"Expected status='success', got {status!r}"
    assert stopped_at is not None, "stopped_at should be non-null after shutdown"


async def test_failed_service_cascade_triggers_shutdown(ha_container: str, tmp_path):
    """A FAILED event for an unknown service cascades through ServiceWatcher and triggers shutdown."""

    class _AlwaysFailingService(Service):
        """A service that always fails on initialize — used to drive the cascade test."""

        async def on_initialize(self) -> None:
            raise RuntimeError("_AlwaysFailingService always fails")

        async def serve(self) -> None:
            pass  # never reached

    config = make_system_config(ha_container, tmp_path)
    config = config.model_copy(update={"service_restart_max_attempts": 1, "service_restart_backoff_seconds": 0.0})
    async with startup_context(config) as hassette:
        shutdown_event = asyncio.Event()

        # Add the always-failing service as a child so ServiceWatcher can find it by class_name
        failing_service = _AlwaysFailingService(hassette, parent=hassette)
        hassette.children.append(failing_service)

        real_shutdown = hassette.shutdown

        async def _stub_shutdown() -> None:
            shutdown_event.set()

        hassette.shutdown = _stub_shutdown  # pyright: ignore[reportAttributeAccessIssue]

        try:
            # Fire a FAILED event — ServiceWatcher will restart once (max_attempts=1),
            # then exhaust retries and call hassette.shutdown() (which is now the stub)
            failed_event = make_service_failed_event(failing_service)
            await hassette.send_event(failed_event.topic, failed_event)

            await wait_for(
                shutdown_event.is_set,
                timeout=30,
                desc="ServiceWatcher to exhaust retries and call shutdown",
            )
        finally:
            hassette.shutdown = real_shutdown  # pyright: ignore[reportAttributeAccessIssue]

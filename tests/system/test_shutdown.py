"""System tests for Hassette shutdown lifecycle."""

import sqlite3
from typing import ClassVar

import pytest

from hassette.exceptions import FatalError
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.test_utils import make_service_failed_event, wait_for
from hassette.types.enums import ResourceStatus, RestartType

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system_destructive]


async def test_clean_shutdown(ha_container: str, tmp_path) -> None:
    """After startup_context exits, Hassette is fully shut down and the session row is finalized."""
    config = make_system_config(ha_container, tmp_path)

    async with startup_context(config) as hassette:
        session_id = hassette.session_id
        db_path = hassette.config.database.path or (hassette.config.data_dir / "hassette.db")

    # After the context exits, assert shutdown completed
    assert hassette.shutdown_completed is True
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


async def test_failed_service_cascade_triggers_fatal_shutdown(ha_container: str, tmp_path) -> None:
    """A FAILED event for a PERMANENT service cascades through ServiceWatcher into a fatal shutdown.

    This is the destructive counterpart to the fatal-exit unit/integration tests — it can only live
    here because it tears the running instance down. It drives a real PERMANENT service to budget
    exhaustion through the real bus (where the CRASHED event is dispatched asynchronously) and proves
    the end-to-end fatal-exit contract that mocks cannot:

    1. ``run_forever()`` raises ``FatalError`` (which maps to a non-zero process exit via run.py), so
       an external supervisor restarts after a fatal crash. startup_context re-raises the
       background task's exception on exit, so the crash surfaces here as ``FatalError``.
    2. The fatal reason is recorded synchronously at the exhaustion decision site, naming the cause.
    3. The crash is persisted to the telemetry session before teardown, so the session is NOT recorded
       as a clean success.
    """

    class _AlwaysFailingService(Service):
        """A PERMANENT service that always fails on initialize — drives the exhaustion/crash path."""

        restart_spec: ClassVar[RestartSpec] = RestartSpec(
            restart_type=RestartType.PERMANENT,
            budget_intensity=1,
            backoff_base_seconds=0.0,
        )

        async def on_initialize(self) -> None:
            raise RuntimeError("_AlwaysFailingService always fails")

        async def serve(self) -> None:
            pass  # never reached

    config = make_system_config(ha_container, tmp_path)
    db_path = config.database.path or (config.data_dir / "hassette.db")
    session_id: int | None = None

    # The FatalError is raised by startup_context's exit (after the in-context assertions run),
    # so the raises block must wrap the whole async-with, not a single call (hence PT012 suppressed).
    with pytest.raises(FatalError, match="PERMANENT"):  # noqa: PT012
        async with startup_context(config) as hassette:
            session_id = hassette.session_id
            # Add the always-failing service as a child so ServiceWatcher can find it by class_name.
            failing_service = _AlwaysFailingService(hassette, parent=hassette)
            hassette.children.append(failing_service)

            # Fire a FAILED event — ServiceWatcher restarts once (budget_intensity=1), then exhausts the
            # budget, records the fatal reason, emits CRASHED, and triggers shutdown. run_forever()
            # unblocks and raises FatalError, which startup_context re-raises on context exit.
            await hassette.send_event(make_service_failed_event(failing_service))

            await wait_for(
                hassette.shutdown_event.is_set,
                timeout=45,
                desc="ServiceWatcher to exhaust retries and trigger fatal shutdown",
            )

            # Recorded synchronously at the exhaustion decision site, before any teardown.
            assert hassette._fatal_shutdown_reason is not None
            assert failing_service.class_name in hassette._fatal_shutdown_reason

    # run_forever() raised FatalError (caught above) → non-zero exit signal. The real teardown ran,
    # finalizing the session. The crashed session must not be recorded as a clean success.
    assert session_id is not None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()

    assert row is not None, "Session row not found"
    assert row[0] != "success", f"Crashed session must not be recorded as success, got {row[0]!r}"

"""Stubs for driving a real ``Hassette`` instance through ``run_forever()`` in integration tests."""

from dataclasses import dataclass
from unittest.mock import AsyncMock

from hassette.core.core import Hassette
from hassette.utils.service_utils import WaveOutcome, WaveResult

WAVE_OK = WaveResult(WaveOutcome.OK)
"""The ``_wait_for_wave`` stub's default result: every startup wave finished and became ready."""


@dataclass(frozen=True)
class RunForeverStubs:
    """The ``AsyncMock``s ``stub_run_forever_collaborators`` installed, typed for assertions."""

    wait_for_wave: AsyncMock
    """Called once per startup wave; the database service's wave comes first."""
    mark_orphaned_sessions: AsyncMock
    create_session: AsyncMock
    shutdown: AsyncMock | None
    """``None`` when ``stub_shutdown=False`` left the real ``shutdown()`` in place."""


def stub_run_forever_collaborators(hassette: Hassette, *, stub_shutdown: bool = True) -> RunForeverStubs:
    """Replace the collaborators ``run_forever()`` awaits during startup with ``AsyncMock``s.

    Stubs ``_wait_for_wave`` (returning ``WAVE_OK``), ``session_manager.mark_orphaned_sessions``,
    ``session_manager.create_session``, and, when ``stub_shutdown`` is true, ``shutdown``. Tests
    that need different behavior set ``side_effect``/``return_value`` on a returned stub.
    Pass ``stub_shutdown=False`` when the test exercises the real ``shutdown()`` path.

    This does not stub ``start()``: it is a module-level function in
    ``hassette.resources.lifecycle``, not a method, and ``run_forever()`` calls the free function
    for every child. Patch it at the call site with ``patch("hassette.core.core.start")`` so real
    children never spawn; reassigning an attribute on the instance has no effect.

    Returns:
        The installed stubs, so tests assert on ``AsyncMock`` types rather than the patched methods.
    """
    stubs = RunForeverStubs(
        wait_for_wave=AsyncMock(return_value=WAVE_OK),
        mark_orphaned_sessions=AsyncMock(),
        create_session=AsyncMock(),
        shutdown=AsyncMock() if stub_shutdown else None,
    )
    hassette._wait_for_wave = stubs.wait_for_wave
    hassette.session_manager.mark_orphaned_sessions = stubs.mark_orphaned_sessions
    hassette.session_manager.create_session = stubs.create_session
    if stubs.shutdown is not None:
        hassette.shutdown = stubs.shutdown  # pyright: ignore[reportAttributeAccessIssue]
    return stubs

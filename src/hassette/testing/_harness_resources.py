"""Resource subclasses the test harness runs in place of their production counterparts."""

from hassette.core.core import Hassette
from hassette.core.state_proxy import StateProxy
from hassette.resources.base import Resource


class HarnessHassette(Hassette):
    """Thin Hassette subclass for use in the test harness.

    Overrides exactly two methods to make the harness lifecycle work:
    - _should_skip_dependency_check: prevents startup from blocking on unmet deps.
    - wait_for_ready: returns True immediately so services do not deadlock during
      harness-controlled startup.
    """

    def _should_skip_dependency_check(self) -> bool:
        return True

    async def wait_for_ready(self, resources: list[Resource] | Resource, timeout: float | None = None) -> bool:
        """Immediately return True (no-op stub).

        In the test harness, services call ``self.hassette.wait_for_ready()``
        during ``on_initialize()``.  The harness controls the lifecycle
        explicitly (``HassetteHarness.start()`` waits on real children via
        the utility function), so dependency waits inside individual services
        must be no-ops — allowing them to block would deadlock the startup
        sequence.

        Note: This no-op stub is NOT the right tool for testing startup
        races (e.g., "what happens when a dependency is not yet ready?").
        For startup race tests, use ``asyncio.Event`` as a gate and inject a
        custom ``wait_for_ready`` side-effect. See
        ``.claude/rules/regression-test-patterns.md`` for the recommended pattern using
        ``AsyncMock(side_effect=lambda _: gate.wait())``.
        """
        return True


class HarnessStateProxy(StateProxy):
    """StateProxy that never installs the periodic poll job.

    Harness tests drive synchronization explicitly, and a background poll would issue
    ``get_states`` calls against the mock API on its own schedule. Without a poll job, a failed
    synchronization falls back to StateProxy's backoff retry instead of waiting for the next poll.
    """

    async def _install_poll_job(self) -> None:
        self.poll_job = None

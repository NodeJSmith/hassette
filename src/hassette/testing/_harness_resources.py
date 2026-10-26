"""Resource subclasses the test harness runs in place of their production counterparts."""

from hassette.core.core import Hassette
from hassette.core.event_stream_service import EventStreamService
from hassette.core.state_proxy import StateProxy
from hassette.resources.base import Resource
from hassette.resources.service import Service


class HarnessHassette(Hassette):
    """Thin Hassette subclass for use in the test harness.

    Overrides these methods to make the harness lifecycle work:
    - should_skip_dependency_check: prevents startup from blocking on unmet deps.
    - wait_for_ready: returns True immediately so services do not deadlock during
      harness-controlled startup.
    - report_service_failure: a no-op, so a required service failing in a shared harness
      never latches a fatal reason or requests shutdown for the tests that follow.
    """

    def should_skip_dependency_check(self) -> bool:
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

    def report_service_failure(self, service: Service, exc: BaseException) -> None:
        """Ignore the report: the service's own status (FAILED or CRASHED) still records the failure."""


class HarnessStateProxy(StateProxy):
    """StateProxy that never installs the periodic poll job.

    Harness tests drive synchronization explicitly, and a background poll would issue
    ``get_states`` calls against the mock API on its own schedule. Without a poll job, a failed
    synchronization falls back to StateProxy's backoff retry instead of waiting for the next poll.
    """

    async def _install_poll_job(self) -> None:
        self.poll_job = None


class HarnessEventStreamService(EventStreamService):
    """EventStreamService variant that suppresses close_streams() for test harness reuse.

    Module-scoped fixtures share a single HarnessHassette across many tests. Some test
    scenarios trigger ``hassette.shutdown()``, which normally closes the anyio memory streams
    inside ``EventStreamService``. Closed streams cannot be reopened, so subsequent tests in
    the same module would receive ``ClosedResourceError`` on every ``send_event`` call.

    By making ``close_streams()`` a no-op here, the streams remain open for the
    lifetime of the harness.  Explicit stream teardown is handled by
    ``HassetteHarness.stop()``, which calls ``_close_streams_now()`` directly —
    the only code path that should close streams in test context.
    """

    async def close_streams(self) -> None:
        """No-op in test context — streams are closed by HassetteHarness.stop() instead."""

    async def _close_streams_now(self) -> None:
        """Close streams unconditionally — bypasses the no-op override above."""
        await super().close_streams()

"""Tests for total shutdown timeout behavior.

Verifies:
- Total timeout caps wall-clock shutdown duration
- _force_terminal() is called on all descendants when total timeout fires
- close_streams() equivalent runs even on total timeout
- The stored teardown report records TOTAL_TIMEOUT and FORCED_TERMINAL
"""

import asyncio

from hassette.config.config import HassetteConfig
from hassette.resources.base import FinalMeta, Resource
from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.test_utils import make_mock_hassette, make_task_bucket
from hassette.test_utils.config import make_test_config
from hassette.test_utils.helpers import SHORT_SHUTDOWN_TIMEOUT_SECONDS
from hassette.types.enums import ResourceStatus

from .conftest import HangingChild, ShutdownCounter, SimpleParent

# Pre-register so FinalMeta allows the _shutdown_body() override on this test helper. Only
# initialize()/shutdown() are @final now — this registration is a defensive no-op kept for
# parity with the rest of the suite, since _shutdown_body() was never @final.
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.TotalTimeoutRoot")
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.RootIdentityResource")
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.SleepingChild")
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.HooksThenHangingChild")
FinalMeta.LOADED_CLASSES.add("tests.unit.resources.lifecycle.test_total_timeout.FailingHookThenHangingChild")


class TotalTimeoutRoot(Resource):
    """Mimics Hassette's root shutdown body: total-timeout-wrapped teardown.

    Uses the same pattern as ``Hassette._shutdown_body()`` to test the
    ``total_shutdown_timeout_seconds`` behavior without requiring the full
    Hassette __init__ machinery.

    Note: this fixture does not model ``COORDINATOR_MARGIN_FRACTION`` — it wraps
    with the full, unshaved ``total_shutdown_timeout_seconds``. That's fine here
    because `make_total_timeout_root()` gives each instance a distinct mock
    `.hassette`, so `resource is resource.hassette` is always False for this
    fixture, and no test built on `TotalTimeoutRoot` reaches
    `_run_shutdown_coordinator()`'s root-identity branch that the margin defends
    against (that branch is covered separately below by `RootIdentityResource`).
    """

    _close_streams_called: bool = False
    _handle_stop_called: bool = False

    @property
    def event_streams_closed(self) -> bool:
        return self._close_streams_called

    async def _close_streams(self) -> None:
        self._close_streams_called = True

    async def _shutdown_body(self) -> "TeardownReport":
        try:
            async with asyncio.timeout(self.hassette.config.lifecycle.total_shutdown_timeout_seconds):
                report = await super()._shutdown_body()
        except TimeoutError:
            self.logger.critical(
                "Total shutdown timeout (%ss) exceeded — forcing termination",
                self.hassette.config.lifecycle.total_shutdown_timeout_seconds,
            )
            for child in self.children:
                child._force_terminal()
            report = TeardownReport(causes=(TeardownCause.TOTAL_TIMEOUT, TeardownCause.FORCED_TERMINAL))
        finally:
            self._handle_stop_called = True
            await self._close_streams()
            self.status = ResourceStatus.STOPPED

        return report


def make_total_timeout_root(total_timeout: float = 0.1, resource_timeout: float = 5) -> TotalTimeoutRoot:
    """Build a `TotalTimeoutRoot` with the lifecycle timeout config set."""
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.total_shutdown_timeout_seconds = total_timeout
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = resource_timeout
    return TotalTimeoutRoot(hassette)


async def test_total_shutdown_timeout_caps_wall_clock():
    """Hassette-style total timeout ensures shutdown completes within budget even when a child hangs."""
    root = make_total_timeout_root(total_timeout=0.2)

    hanging = root.add_child(HangingChild)
    normal = root.add_child(ShutdownCounter)

    await root.initialize()
    await hanging.initialize()
    await normal.initialize()

    start = asyncio.get_event_loop().time()
    report = await root.shutdown()
    elapsed = asyncio.get_event_loop().time() - start

    # Should complete in roughly total_shutdown_timeout_seconds (0.2s), not
    # resource_shutdown_timeout_seconds (5s). The 3s cap gives generous margin
    # for CI runner variability while still catching the 5s per-resource path.
    assert elapsed < 3.0, f"Shutdown took {elapsed:.2f}s — total timeout should have capped it"
    assert root.shutdown_completed is True
    assert hanging.shutdown_completed is True
    assert report.is_restart_safe is False
    assert TeardownCause.TOTAL_TIMEOUT in report.causes


async def test_total_timeout_force_patches_all_descendants():
    """On total timeout, _force_terminal() is called recursively on all descendants."""
    root = make_total_timeout_root()

    hanging = root.add_child(HangingChild)
    grandchild = hanging.add_child(SimpleParent)

    await root.initialize()
    await hanging.initialize()
    await grandchild.initialize()

    await root.shutdown()

    # All descendants should be force-terminated
    assert hanging.shutdown_completed is True
    assert hanging.status == ResourceStatus.STOPPED
    assert grandchild.shutdown_completed is True
    assert grandchild.status == ResourceStatus.STOPPED


async def test_total_timeout_finally_always_closes_streams():
    """close_streams() equivalent is called even when the total timeout fires."""
    root = make_total_timeout_root()
    root.add_child(HangingChild)

    await root.initialize()

    await root.shutdown()

    assert root._close_streams_called is True, "close_streams must be called even on total timeout"


async def test_total_timeout_report_records_forced_terminal_and_total_timeout():
    """The stored teardown report records both TOTAL_TIMEOUT and FORCED_TERMINAL on timeout."""
    root = make_total_timeout_root()
    root.add_child(HangingChild)

    await root.initialize()

    report = await root.shutdown()

    assert report.is_restart_safe is False
    assert TeardownCause.TOTAL_TIMEOUT in report.causes
    assert TeardownCause.FORCED_TERMINAL in report.causes
    assert root.teardown_report == report


class RootIdentityResource(Resource):
    """A ``Resource`` whose ``.hassette`` is itself, mimicking ``Hassette.__init__``'s
    self-reference (``super().__init__(self, ..., parent=self)``).

    Exercises the root-identity branch in ``_run_shutdown_coordinator``
    (``resource is resource.hassette``), which bounds the shutdown coordinator's outer wait
    with ``total_shutdown_timeout_seconds`` instead of the generic
    ``resource_shutdown_timeout_seconds`` used for every non-root resource.
    """

    _shutdown_sleep: float = 0.0
    loop_thread_id: int | None = None
    """Satisfies ``_HassetteP``'s ``loop_thread_id`` field for ``lifecycle.cancel()``/``start()``,
    which read it unconditionally off ``resource.hassette`` -- and here ``resource.hassette`` is
    this instance itself. ``None`` mirrors the real ``Hassette``'s own pre-``run_forever()``
    default, which both functions already treat as "unknown, do not redispatch."""

    def __init__(self, config: HassetteConfig) -> None:
        self.config = config
        self.event_streams_closed = False
        task_bucket = make_task_bucket()
        super().__init__(self, task_bucket=task_bucket, parent=self)

    @property
    def unique_name(self) -> str:
        return "RootIdentityResource"

    async def send_event(self, event: object) -> None:
        """No-op stand-in for `Hassette.send_event` — the event bus isn't under test here."""

    async def _shutdown_body(self) -> "TeardownReport":
        await asyncio.sleep(self._shutdown_sleep)
        return await super()._shutdown_body()


class SleepingChild(Resource):
    """Non-root resource whose shutdown body sleeps for a configurable duration.

    Companion fixture to `RootIdentityResource` — same shape, but `resource is resource.hassette`
    is always `False`, so it exercises the generic (non-root) timeout branch. Sleeps directly in
    ``_shutdown_body()`` rather than in an ``on_shutdown()`` hook, matching
    ``RootIdentityResource``'s own override -- shutdown hooks are now individually bounded by the
    shared shutdown budget (``bound_to_shutdown_budget=True`` in ``base.py``'s
    ``_shutdown_body()``), which would resolve a hook-level sleep from *inside* the body before
    the coordinator's own outer wait ever gets a chance to fire, defeating the point of this
    fixture as a test of the outer-wait config selection.
    """

    _shutdown_sleep: float = 0.0

    async def _shutdown_body(self) -> "TeardownReport":
        await asyncio.sleep(self._shutdown_sleep)
        return await super()._shutdown_body()


class HooksThenHangingChild(Resource):
    """Non-root resource whose shutdown hooks complete normally, but the stage after hooks
    (task-bucket cancel / cleanup() / child propagation) sleeps for a configurable duration.

    Companion fixture to `SleepingChild` — that one sleeps *before* hooks run (hooks never get a
    chance to complete); this one sleeps *after* hooks already ran, by overriding
    `_run_post_hook_shutdown_stage()` instead of `_shutdown_body()` itself. Proves the two cases
    classify differently once `_shutdown_hooks_completed` is in the picture.
    """

    _post_hook_sleep: float = 0.0

    async def _run_post_hook_shutdown_stage(self) -> "TeardownReport":
        await asyncio.sleep(self._post_hook_sleep)
        return await super()._run_post_hook_shutdown_stage()


class FailingHookThenHangingChild(Resource):
    """Non-root resource whose `on_shutdown()` hook raises, and whose post-hook stage then
    sleeps for a configurable duration.

    `run_hooks(..., continue_on_error=True)` catches the raise and lets `_shutdown_body()`
    continue normally -- but that means the resulting `SHUTDOWN_HOOK_FAILED` evidence lives only
    in `Resource._shutdown_body()`'s own local `hook_report` until it returns. If the post-hook
    stage below then hangs past the outer coordinator deadline, this whole body task gets
    cancelled before it ever returns that report, and the hook failure would otherwise be
    silently lost. Proves `_shutdown_hooks_completed` stays `False` here (not just "hooks never
    got a chance to run", but also "a hook raised"), so `_force_terminal()` still records
    `FORCED_TERMINAL` for real instead of letting this misclassify as timeout-only.
    """

    _post_hook_sleep: float = 0.0

    async def on_shutdown(self) -> None:
        raise RuntimeError("on_shutdown boom")

    async def _run_post_hook_shutdown_stage(self) -> "TeardownReport":
        await asyncio.sleep(self._post_hook_sleep)
        return await super()._run_post_hook_shutdown_stage()


async def test_root_identity_uses_total_timeout_not_resource_timeout(tmp_path):
    """A root resource (`resource is resource.hassette`) is bounded by
    `total_shutdown_timeout_seconds`, not `resource_shutdown_timeout_seconds` — even when the
    per-resource timeout is deliberately set smaller (matching the real 10s/30s production
    relationship, scaled down here for test speed).
    """
    config = make_test_config(data_dir=tmp_path)
    config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    config.lifecycle.total_shutdown_timeout_seconds = 0.3
    root = RootIdentityResource(config)
    root._shutdown_sleep = 0.2  # longer than the 0.1s resource timeout, shorter than the 0.3s total

    await root.initialize()

    start = asyncio.get_event_loop().time()
    report = await root.shutdown()
    elapsed = asyncio.get_event_loop().time() - start

    # Proves the sleep wasn't cut short by the smaller resource timeout.
    assert elapsed >= 0.2, f"Shutdown completed in {elapsed:.2f}s — body should have run the full 0.2s sleep"
    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT not in report.causes
    assert report.is_restart_safe is True


async def test_non_root_with_same_timeouts_still_force_terminates(tmp_path):
    """A non-root resource with the identical 0.1s/0.3s timeout split still gets force-terminated
    at the smaller resource timeout — proving the root-identity branch is root-specific and
    doesn't silently widen the shutdown budget for every resource.
    """
    hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.3
    child = SleepingChild(hassette)
    child._shutdown_sleep = 0.2  # longer than the 0.1s resource timeout the non-root branch uses

    await child.initialize()

    report = await child.shutdown()

    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT in report.causes
    assert report.is_restart_safe is False
    # SleepingChild sleeps *before* calling super()._shutdown_body(), so shutdown hooks never ran
    # before the outer timeout fires -- FORCED_TERMINAL must be recorded for real here, since
    # _force_terminal() skips on_shutdown() and this resource's own release logic never got a
    # chance to run. See test_body_timeout_after_hooks_complete_stays_timeout_only below for the
    # companion case (hooks already ran) where FORCED_TERMINAL stays suppressed instead.
    assert TeardownCause.FORCED_TERMINAL in report.causes
    assert report.is_timeout_only_refusal is False


async def test_body_timeout_after_hooks_complete_stays_timeout_only(tmp_path):
    """A resource whose shutdown hooks (before_shutdown/on_shutdown/after_shutdown) already
    completed before the outer timeout fires stays timeout-only-eligible -- FORCED_TERMINAL must
    stay suppressed, because the resource's own release logic already ran and whatever remains
    (task-bucket cancel, cleanup(), child propagation) already produces its own evidence through
    the normal paths. Companion to test_non_root_with_same_timeouts_still_force_terminates above,
    where hooks never got a chance to run and FORCED_TERMINAL is recorded for real instead.
    """
    hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.3
    child = HooksThenHangingChild(hassette)
    child._post_hook_sleep = 0.2  # longer than the 0.1s resource timeout, after hooks already ran

    await child.initialize()

    report = await child.shutdown()

    assert child._shutdown_hooks_completed is True
    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT in report.causes
    assert report.is_restart_safe is False
    assert TeardownCause.FORCED_TERMINAL not in report.causes
    assert report.is_timeout_only_refusal is True


async def test_body_timeout_after_hook_failure_still_force_terminates(tmp_path):
    """A resource whose on_shutdown() hook raised, then whose post-hook stage hangs past the
    outer timeout, must still escalate -- the handled hook failure is real negative evidence
    (not just "still running") that must not be silently discarded just because the body task
    that recorded it locally gets cancelled before returning its report.
    """
    hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.3
    child = FailingHookThenHangingChild(hassette)
    child._post_hook_sleep = 0.2  # longer than the 0.1s resource timeout, after on_shutdown() raised

    await child.initialize()

    report = await child.shutdown()

    assert child._shutdown_hooks_completed is False
    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT in report.causes
    assert TeardownCause.FORCED_TERMINAL in report.causes
    assert report.is_restart_safe is False
    assert report.is_timeout_only_refusal is False


async def test_body_timeout_folds_in_forced_children(tmp_path):
    """A resource whose own body times out before ever reaching its children-shutdown stage
    still force-terminates live children via _force_terminal()'s cascade -- their outcome must be
    folded into the parent's report as CHILD_RESTART_UNSAFE, not silently discarded, or a parent
    with force-terminated, hook-skipped children could misclassify as is_timeout_only_refusal.
    """
    hassette = make_mock_hassette(data_dir=tmp_path, sealed=False)
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = SHORT_SHUTDOWN_TIMEOUT_SECONDS
    hassette.config.lifecycle.total_shutdown_timeout_seconds = 0.3

    parent = SleepingChild(hassette)
    parent._shutdown_sleep = 0.2  # longer than the 0.1s resource timeout -- never reaches children
    child = parent.add_child(ShutdownCounter)

    await parent.initialize()  # also initializes child (Resource._initialize_body() auto-inits children)

    report = await parent.shutdown()

    assert TeardownCause.SHUTDOWN_BODY_TIMED_OUT in report.causes
    assert TeardownCause.CHILD_RESTART_UNSAFE in report.causes
    assert child.unique_name in report.affected_resources
    assert report.is_restart_safe is False
    assert report.is_timeout_only_refusal is False, (
        "a parent whose body timed out AND whose live child was force-terminated must not "
        "classify as timeout-only -- the child's FORCED_TERMINAL evidence must block degrade"
    )
    assert child.shutdown_count == 0, "child was force-terminated, not gracefully shut down"

    child_report = child.teardown_report
    assert child_report is not None
    assert TeardownCause.FORCED_TERMINAL in child_report.causes

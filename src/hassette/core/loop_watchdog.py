"""Tier 1 loop-responsiveness watchdog for blocking-IO detection.

Detects event-loop stalls caused by blocking code on the loop thread and emits a
``HassetteBlockingIOWarning`` naming the offending app.

**Mechanism: Candidate B (off-loop daemon thread)**

Two cooperating parts:

1. **In-loop tick updater** — a lightweight recurring ``loop.call_later`` callback that writes
   ``time.monotonic()`` to a thread-visible timestamp and reschedules itself. It runs only when
   the loop is free; during a freeze it cannot run, so the timestamp goes stale.

2. **Daemon thread** — wakes on a sub-threshold interval and checks ``now - last_tick``. When
   that exceeds ``lag_threshold_seconds`` AND the executor's marker is non-None, the loop is
   frozen *inside* that execution → attribute the stall to it. The daemon reads the marker
   *during* the freeze (the handler's ``finally`` has not run yet), which is why an off-loop
   thread is required.

Detection is gated on **tick staleness**, never on marker age. A handler doing
``await asyncio.sleep(30)`` keeps the loop free, so the in-loop tick keeps advancing → no
stall flagged even though the marker has been set for 30s. Only a synchronous block starves
the tick. This satisfies FR#9 / AC#3.

**Warn-after, one warning per episode.** A freeze is one *episode*: the daemon captures the
offending marker and a stack snapshot when the stall is first detected (while the loop is
still frozen, so the snapshot shows the blocking line), then emits exactly one warning when
the loop **recovers**, reporting the full stall duration (the gap the tick was starved). This
is "report after the stall" (FR#3) and makes the reported duration ≈ the block length (AC#1).
A block that never recovers before shutdown is flushed once in ``stop()``.

Architecture reference: design/specs/074-blocking-io-detection/design.md §"Tier 1"
"""

import contextlib
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING

from hassette.core.block_io_guard import resolve_blocking_io_behavior
from hassette.exceptions import HassetteBlockingIOWarning
from hassette.types.enums import BlockingIOBehavior
from hassette.utils.source_capture import is_internal_frame

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor, ExecutionMarker

# The daemon polls several times per watchdog interval so it notices a stall promptly
# without the in-loop tick and the poll aliasing into a missed detection.
_POLL_SUBDIVISIONS = 3
_MAX_STACK_DEPTH = 30


@dataclass(frozen=True)
class WatchdogEvent:
    """Detected stall event — structured for T05 DB persistence.

    Carries enough attribution that the persistence layer (T05) can write a
    ``blocking_events`` row without re-reading any live state. The watchdog
    clears ``current_execution`` on the loop thread after the block, so T05
    must consume this snapshot, not re-read the executor.
    """

    app_key: str | None
    """App key that held the loop, or ``None`` for framework/unattributed stalls."""

    instance_name: str | None
    """Human-readable instance name, or ``None``."""

    instance_index: int | None
    """0-based instance index from the execution marker, or ``None`` when the marker had none."""

    execution_id: str
    """UUIDv7 string of the execution that froze the loop."""

    stall_duration_ms: float
    """Stall duration in milliseconds — the span the in-loop tick was starved (≈ the block length)."""

    tier: str
    """Always ``"watchdog"`` for Tier 1 events."""

    stack_text: str | None
    """Loop-thread stack snapshot taken *during* the freeze (non-framework frames), or ``None``."""

    detected_at: float
    """``time.time()`` wall-clock timestamp when the stall was detected."""


class LoopWatchdog:
    """Always-on Tier 1 loop-responsiveness watchdog.

    Installs a lightweight in-loop tick callback and a daemon thread that monitors
    tick staleness. A freeze is captured (marker + stack) on first detection and
    reported once on recovery with the full duration. Cleans up completely on stop.

    Usage::

        watchdog = LoopWatchdog(hassette, loop=loop, loop_thread_id=thread_id, executor=executor)
        watchdog.start()   # idempotent
        # ... runtime ...
        watchdog.stop()    # idempotent; joins daemon thread and cancels tick callback
    """

    def __init__(
        self,
        hassette: "Hassette",
        *,
        loop: "asyncio.AbstractEventLoop",
        loop_thread_id: int,
        executor: "CommandExecutor",
        on_stall: "Callable[[WatchdogEvent], object] | None" = None,
    ) -> None:
        """Construct the watchdog.

        Args:
            hassette: The running Hassette instance (used for config and app resolution).
            loop: The event loop to watch.
            loop_thread_id: ``threading.get_ident()`` of the loop thread.
            executor: The ``CommandExecutor`` whose ``current_execution`` marker is read for
                attribution.
            on_stall: Optional callback invoked once per stall episode for persistence.

                Threading contract: ``on_stall`` is called **from the off-loop daemon thread**,
                not the event-loop thread. It must be non-blocking and thread-safe, and it must
                not call async functions or acquire non-reentrant locks directly. To run work on
                the loop thread (e.g. a DB write), marshal it with ``loop.call_soon_threadsafe``.
                Exceptions raised by ``on_stall`` are caught and logged at debug — they never
                kill the daemon — but a callback that blocks will stall detection.
        """
        self._hassette = hassette
        self._loop = loop
        self._loop_thread_id = loop_thread_id
        self._executor = executor
        self._on_stall = on_stall

        cfg = hassette.config.blocking_io
        self._lag_threshold = cfg.lag_threshold_seconds
        self._check_interval = cfg.watchdog_interval_seconds / _POLL_SUBDIVISIONS
        self._capture_stack = cfg.capture_stack_on_block

        # Tick timestamp — written by the in-loop callback, read by the daemon thread.
        # A single float attribute rebind is atomic under the GIL, so no lock is needed.
        self._last_tick: float = time.monotonic()

        # Daemon-thread lifecycle
        self._stop_event = threading.Event()
        self._daemon_thread: threading.Thread | None = None

        # Idempotency guard
        self._started = False

        # In-loop handle — stored so stop() can cancel whatever tick is currently pending.
        self._tick_handle: asyncio.TimerHandle | None = None

        # Open-episode state: set when a freeze is first detected (marker + stack captured
        # live during the freeze, frozen_since = last good tick), cleared when it recovers
        # and the single warning is emitted.
        self._stall_marker: ExecutionMarker | None = None
        self._stall_frozen_since: float = 0.0
        self._stall_stack: str | None = None

    def start(self) -> None:
        """Install the tick callback and start the daemon thread. Idempotent."""
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._last_tick = time.monotonic()
        # Schedule the first in-loop tick — the callback reschedules itself.
        self._tick_handle = self._loop.call_later(self._check_interval, self._tick)
        # Start the off-loop daemon thread.
        self._daemon_thread = threading.Thread(
            target=self._daemon_body,
            name="hassette-loop-watchdog",
            daemon=True,
        )
        self._daemon_thread.start()

    def stop(self) -> None:
        """Stop the watchdog. Idempotent. Joins the daemon thread and cancels the tick callback."""
        if not self._started:
            return
        self._started = False
        # Signal the daemon to exit.
        self._stop_event.set()
        # Cancel the pending call_later handle so no callback remains.
        if self._tick_handle is not None:
            self._tick_handle.cancel()
            self._tick_handle = None
        # Join the daemon thread. The ceiling is one poll cycle plus slack — bounded by the
        # watchdog interval, NOT by lag_threshold (a large threshold must not stall shutdown).
        # daemon_done is True when no daemon could be holding the open episode: either none was
        # started, or the join confirmed it exited. It is False only when the join timed out and
        # the daemon is still alive — in which case the daemon owns the episode and may emit it
        # itself on recovery, so flushing here too would double-report.
        daemon_done = True
        if self._daemon_thread is not None:
            self._daemon_thread.join(timeout=self._check_interval * 3 + 1.0)
            # Daemon is daemonic, so a timed-out join cannot block process exit; drop the ref.
            daemon_done = not self._daemon_thread.is_alive()
            self._daemon_thread = None
        # Flush a still-open episode: a block that never recovered before shutdown is still
        # reported once, rather than silently dropped. Guarded on daemon_done so we never race
        # the still-running daemon over the same episode (see above).
        if daemon_done and self._stall_marker is not None:
            # Runs on the loop thread during teardown; an escalated warning or a closing-loop
            # persist error must not derail shutdown — but a drop should be visible, not silent.
            try:
                self._emit_stall(self._stall_marker, time.monotonic() - self._stall_frozen_since, self._stall_stack)
            except Exception as exc:
                LOGGER.debug("Failed to flush open stall episode at shutdown: %s", exc)
        # Release the episode refs even when daemon_done is False (flush skipped above): the
        # daemon is daemonic and dies at process exit, so no surviving reader can race the clear.
        self._stall_marker = None
        self._stall_stack = None

    def _tick(self) -> None:
        """Advance the heartbeat timestamp and reschedule."""
        self._last_tick = time.monotonic()
        if not self._stop_event.is_set():
            # Overwrite _tick_handle with the newly scheduled call so stop() always holds the
            # currently-pending handle and cancels it, regardless of how many ticks have fired.
            self._tick_handle = self._loop.call_later(self._check_interval, self._tick)

    def _daemon_body(self) -> None:
        """Main loop of the daemon watchdog thread.

        Captures the offending execution (and a stack snapshot) DURING a freeze, while the
        marker is still live, then reports the stall AFTER the loop recovers so the duration
        reflects the full block (FR#3 warn-after, AC#1 duration ≈ T). One episode → one warning.
        """
        while not self._stop_event.is_set():
            time.sleep(self._check_interval)
            if self._stop_event.is_set():
                break
            # Never let a per-iteration error kill the daemon — a dead daemon means Tier 1
            # silently stops detecting for the rest of the process. Swallow and keep polling.
            try:
                lag = time.monotonic() - self._last_tick
                if lag >= self._lag_threshold:
                    # Tick is stale — the loop is frozen. Capture the offender once, on the first
                    # poll that sees the freeze, while its marker and stack are still live.
                    if self._stall_marker is None:
                        marker: ExecutionMarker | None = self._executor.current_execution
                        if marker is not None:
                            self._stall_marker = marker
                            self._stall_frozen_since = self._last_tick
                            self._stall_stack = self._capture_loop_stack() if self._capture_stack else None
                    continue
                # Loop is responsive. If an episode is open, it just recovered — report it now
                # with the full stall duration (the span the tick was starved), then close it.
                if self._stall_marker is not None:
                    duration = self._last_tick - self._stall_frozen_since
                    self._emit_stall(self._stall_marker, duration, self._stall_stack)
                    self._stall_marker = None
                    self._stall_stack = None
            except Exception:
                # Defensive: drop the open episode so a poisoned marker can't wedge detection.
                # Log first so the discarded stall marker and stack leave a diagnostic trail.
                LOGGER.debug(
                    "Loop watchdog poll iteration failed — dropping open stall episode (marker and stack cleared)",
                    exc_info=True,
                )
                self._stall_marker = None
                self._stall_stack = None

    def _capture_loop_stack(self) -> str | None:
        """Capture and filter the loop thread's current stack frames.

        Returns a formatted string of non-internal frames, or ``None`` when
        no frame is available or readable.
        """
        try:
            frames = sys._current_frames()
        except Exception:
            return None
        frame = frames.get(self._loop_thread_id)
        if frame is None:
            return None
        # Walk the frame chain and collect non-internal frames.
        lines: list[str] = []
        f = frame
        depth = 0
        while f is not None and depth < _MAX_STACK_DEPTH:
            if not is_internal_frame(f):
                name = f.f_globals.get("__name__", "<unknown>")
                co = f.f_code
                lines.append(f'  File "{co.co_filename}", line {f.f_lineno}, in {co.co_name} ({name})')
            f = f.f_back
            depth += 1
        if not lines:
            return None
        return "\n".join(lines)

    def _emit_stall(self, marker: "ExecutionMarker", stall_seconds: float, stack_text: str | None) -> None:
        """Build a WatchdogEvent for a recovered stall and emit the warning."""
        event = WatchdogEvent(
            app_key=marker.app_key,
            instance_name=marker.instance_name,
            instance_index=marker.instance_index,
            execution_id=marker.execution_id,
            stall_duration_ms=stall_seconds * 1000.0,
            tier="watchdog",
            stack_text=stack_text,
            detected_at=time.time(),
        )
        self._emit(marker, event)

    def _emit(self, marker: "ExecutionMarker", event: WatchdogEvent) -> None:
        """Resolve behavior and emit the warning for a detected stall.

        Resolution: per-app ``AppConfig.blocking_io_behavior`` → global
        ``HassetteConfig.blocking_io.behavior`` → WARN (hardcoded default).

        WARN and ERROR both call ``warnings.warn``. ERROR escalates only via the user's
        ``filterwarnings("error")`` — Tier 1 never raises unconditionally.

        ``IGNORE`` suppresses both the warning AND persistence — no ``blocking_events`` row is
        written. This is the deliberate exception to persist-before-warn (see below).
        """
        # Resolve the owner App instance for per-app behavior resolution.
        owner: object = self._hassette
        if marker.app_key is not None:
            with contextlib.suppress(Exception):
                app_inst = self._hassette.app_handler.get(marker.app_key, marker.instance_index or 0)
                if app_inst is not None:
                    owner = app_inst

        behavior = resolve_blocking_io_behavior(owner)
        if behavior is BlockingIOBehavior.IGNORE:
            # IGNORE returns BEFORE persistence: an ignored stall leaves no audit trail by design.
            # The persist-before-warn rule below applies only to WARN/ERROR.
            return

        app_label = marker.app_key or "<framework>"
        inst_label = f" ({marker.instance_name})" if marker.instance_name else ""
        msg = (
            f"Blocking I/O detected on the event loop — "
            f"app: {app_label}{inst_label}, "
            f"execution: {marker.execution_id}, "
            f"stall: {event.stall_duration_ms:.0f}ms"
        )
        if event.stack_text:
            msg += f"\nLoop thread stack (non-framework frames):\n{event.stack_text}"

        # Persist FIRST (T05), for WARN/ERROR only (IGNORE already returned above): warnings.warn
        # below can raise on a user filterwarnings("error") escalation, which would otherwise skip
        # the row — but a non-ignored stall happened and must be recorded regardless of escalation.
        # on_stall marshals onto the loop; a closed/stopped loop at shutdown raises RuntimeError.
        # Catch it so the escalation can't kill the daemon thread, but log at debug so the dropped
        # persist is visible rather than silent.
        if self._on_stall is not None:
            try:
                self._on_stall(event)
            except Exception as exc:
                LOGGER.debug("Failed to persist stall event (loop unavailable at shutdown?): %s", exc)

        # Emit on the daemon thread. WARN and ERROR both go through warnings.warn; if the user's
        # filter escalates it to an error, warnings.warn raises — swallow it so the escalation
        # cannot kill the watchdog thread. Tier 1 is warn-after and never propagates a raise
        # (FR#3); call-site interception is Tier 2's job.
        with contextlib.suppress(HassetteBlockingIOWarning):
            warnings.warn(msg, HassetteBlockingIOWarning, stacklevel=1)

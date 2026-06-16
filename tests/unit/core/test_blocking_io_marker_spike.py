"""Watchdog-attribution spike for blocking-IO detection (T02).

Resolves the make-or-break design question (design.md `## Open Questions` → "watchdog
mechanism"): which Tier 1 mechanism attributes a loop freeze to the *correct* app.

- **Candidate A** — an in-loop ``loop.call_later`` heartbeat. It can only run when the loop
  is free, so it fires *after* the freeze clears, by which point the marker is already cleared
  or rebound to the next execution. It cannot name the blocker.
- **Candidate B** — an off-loop daemon thread. It reads the thread-visible marker *during* the
  freeze (the handler's ``finally`` has not run), so it names the blocker by construction.

These tests prove B wins under the AC#2 condition (another execution scheduled immediately
after the blocking one) and pin the marker invariants T03 builds on. The Candidate-A code here
is test-scoped contrast, not a production prototype — T03 ships only the daemon watchdog.

Covers:
    FR#4 — attribution names the execution that held the loop during the stall, not the next one
    AC#2 — a time.sleep block with another execution scheduled immediately after is attributed
           to the time.sleep caller's app
"""

import asyncio
import threading
import time

import pytest

from hassette.core.command_executor import ExecutionMarker

from .conftest import make_executor

# ---------------------------------------------------------------------------
# Deterministic invariant guard (no timing) — the marker is cross-thread readable
# while bound and cleared on unbind. This is the stable guarantee T03 inherits.
# ---------------------------------------------------------------------------


def test_marker_published_on_bind_and_cleared_on_unbind() -> None:
    """The marker names the bound execution and resets to None on unbind."""
    executor = make_executor()
    executor.hassette.app_handler.get.return_value = None  # keep instance_name=None

    assert executor.current_execution is None  # idle before any execution

    execution_id, token = executor.bind_execution_context("kitchen_lights", 0)
    marker = executor.current_execution
    assert isinstance(marker, ExecutionMarker)
    assert marker.app_key == "kitchen_lights"
    assert marker.execution_id == execution_id
    assert marker.instance_name is None

    executor.unbind_execution_context(token)
    assert executor.current_execution is None


def test_marker_read_during_block_names_blocker_not_next_execution() -> None:
    """A reader that samples the marker *during* a block sees the blocker; a reader that samples
    *after* unbind sees None, then the next execution — never the blocker (FR#4, AC#2).

    Models the timing difference between the two candidates with deterministic gates rather than
    wall-clock sleeps, so the invariant is pinned without flakiness.
    """
    executor = make_executor()
    executor.hassette.app_handler.get.return_value = None

    candidate_b_read: list[ExecutionMarker | None] = []  # off-loop: reads during the block
    block_in_progress = threading.Event()
    reader_done = threading.Event()

    def off_loop_reader() -> None:
        block_in_progress.wait(timeout=5)
        candidate_b_read.append(executor.current_execution)  # marker is live here
        reader_done.set()

    reader = threading.Thread(target=off_loop_reader, daemon=True)
    reader.start()

    # The blocking execution holds the loop thread.
    block_exec_id, block_token = executor.bind_execution_context("blocking_app", 0)
    block_in_progress.set()  # the off-loop reader samples now, mid-block
    assert reader_done.wait(timeout=5), "off-loop reader did not run"
    executor.unbind_execution_context(block_token)

    # Candidate A fires only now, after the freeze cleared: the marker is None.
    candidate_a_after_unbind = executor.current_execution

    # The next execution, scheduled immediately after the block.
    next_exec_id, next_token = executor.bind_execution_context("next_app", 0)
    candidate_a_if_later = executor.current_execution  # if A fires even later -> next_app
    executor.unbind_execution_context(next_token)

    # Candidate B (off-loop, mid-block) attributed the freeze to the blocking app.
    assert candidate_b_read[0] is not None
    assert candidate_b_read[0].app_key == "blocking_app"
    assert candidate_b_read[0].execution_id == block_exec_id

    # Candidate A (in-loop, post-freeze) never sees the blocker: None, then the next app.
    assert candidate_a_after_unbind is None
    assert candidate_a_if_later is not None
    assert candidate_a_if_later.app_key == "next_app"
    assert candidate_a_if_later.execution_id == next_exec_id


# ---------------------------------------------------------------------------
# Realistic spike — a real event loop, a real time.sleep freezing the loop thread,
# a real loop.call_later heartbeat (Candidate A) and a real daemon thread (Candidate B).
# This is the empirical evidence behind the design decision.
# ---------------------------------------------------------------------------


# A real time.sleep on the loop thread would freeze a shared session-scoped loop and could
# trip timeouts in neighbouring async tests; pin this one to its own function-scoped loop.
@pytest.mark.asyncio(loop_scope="function")
async def test_spike_daemon_attributes_block_heartbeat_cannot() -> None:
    """With a real time.sleep freezing the loop, the daemon thread (B) names the blocker and the
    in-loop heartbeat (A) cannot — it is starved during the freeze (FR#4, AC#2)."""
    executor = make_executor()
    executor.hassette.app_handler.get.return_value = None
    loop = asyncio.get_running_loop()

    threshold = 0.15
    block_duration = 0.45

    daemon_attribution: list[ExecutionMarker] = []  # off-loop, reads live during the freeze
    heartbeat_attribution: list[ExecutionMarker] = []  # in-loop, reads on each fire
    heartbeat_fires = 0  # proves the heartbeat was a live mechanism, not silently absent
    stop = threading.Event()
    last_tick = time.monotonic()

    def daemon_watchdog() -> None:
        # Candidate B: off-loop. When the in-loop tick goes stale, the loop is frozen — read the
        # live marker to name the execution holding it.
        while not stop.is_set():
            time.sleep(threshold / 3)
            if time.monotonic() - last_tick > threshold:
                marker = executor.current_execution
                if marker is not None and not daemon_attribution:
                    daemon_attribution.append(marker)

    watchdog = threading.Thread(target=daemon_watchdog, daemon=True)
    watchdog.start()

    def heartbeat() -> None:
        # In-loop tick updater; doubles as Candidate A (samples the marker each time it fires).
        nonlocal last_tick, heartbeat_fires
        last_tick = time.monotonic()
        heartbeat_fires += 1
        marker = executor.current_execution
        if marker is not None:
            heartbeat_attribution.append(marker)
        if not stop.is_set():
            loop.call_later(threshold / 3, heartbeat)

    loop.call_later(threshold / 3, heartbeat)
    await asyncio.sleep(threshold)  # let the heartbeat establish ticking

    # The blocking execution freezes the loop thread with a real time.sleep. ASYNC251 is the very
    # thing under test here — a sync sleep stalling the loop — so the block is deliberate.
    block_exec_id, block_token = executor.bind_execution_context("blocking_app", 0)
    time.sleep(block_duration)  # noqa: ASYNC251 — intentional loop freeze; this is what we detect
    executor.unbind_execution_context(block_token)

    # The next execution, scheduled immediately after.
    _next_exec_id, next_token = executor.bind_execution_context("next_app", 0)
    await asyncio.sleep(0)  # let any pending heartbeat fire now, post-freeze
    executor.unbind_execution_context(next_token)

    stop.set()
    await asyncio.sleep(threshold)
    watchdog.join(timeout=2)

    # Candidate B read the live marker during the freeze and named the blocker.
    assert daemon_attribution, "daemon thread failed to observe the freeze"
    assert daemon_attribution[0].app_key == "blocking_app"
    assert daemon_attribution[0].execution_id == block_exec_id

    # Candidate A was a live, firing mechanism (non-vacuous), yet starved during the freeze, so it
    # never read the blocker's marker — the assertion below is meaningful, not trivially empty.
    assert heartbeat_fires >= 2
    assert all(m.app_key != "blocking_app" for m in heartbeat_attribution)

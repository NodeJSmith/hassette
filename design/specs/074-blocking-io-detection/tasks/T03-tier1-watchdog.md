---
task_id: "T03"
title: "Build Tier 1 loop-responsiveness watchdog (warn-after)"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#3", "FR#9", "AC#1", "AC#3"]
---

## Summary
Build the always-on Tier 1 watchdog using the mechanism chosen in T02 and the marker it added. The watchdog measures event-loop responsiveness, detects stalls past the configured threshold, names the offending app/handler via the marker (and a stack snapshot on severe stalls), and emits a `HassetteBlockingIOWarning` per the resolved behavior — defaulting to warn-after. It must distinguish a real loop block from legitimate slow async work, and never touch `loop.set_debug`.

## Prompt
Implement the Tier 1 watchdog described in `design/specs/074-blocking-io-detection/design.md`, `## Architecture` → "Tier 1 — always-on loop-responsiveness watchdog". Use the mechanism T02 selected and recorded in the design doc.

1. **Watchdog module** — create the Tier 1 module (`src/hassette/core/` — finalize the name from T02's decision, e.g. `loop_watchdog.py`). It measures loop responsiveness via the chosen mechanism (heartbeat lag or daemon-thread tick observation), with the interval and threshold from `HassetteConfig.blocking_io` (`watchdog_interval_seconds`, `lag_threshold_seconds`).
2. **Detection + attribution** — when responsiveness degrades past the threshold, read the thread-visible marker (from T02) to name the app/handler/job and compute the stall duration. When `capture_stack_on_block` is set and the stall is severe, capture `sys._current_frames()[loop_thread_id]` filtered through `is_internal_frame` (from `utils/source_capture.py`) for the offending frames.
3. **Emission** — emit exactly one `HassetteBlockingIOWarning` per detected stall, naming app/handler and stall duration, via `warnings.warn(..., HassetteBlockingIOWarning, stacklevel=1)`. Resolve behavior with the T01 resolver: `IGNORE` suppresses, `WARN`/`ERROR` both emit (`ERROR` escalates only via the user's `filterwarnings("error")`). Default behavior is warn-after — never raise from Tier 1.
4. **Install/teardown** — install the watchdog in `src/hassette/core/core.py` `run_forever` after `self._loop_thread_id` is captured (line 449), gated on `blocking_io.watchdog_enabled`. Tear it down on shutdown so no task/thread remains. Install must be idempotent.
5. **Tests** — unit + integration in `tests/`. A handler that blocks (`time.sleep(T)`, T past threshold) produces exactly one warning naming its app with duration ≈ T (AC#1). A handler that `await asyncio.sleep(T)` produces no warning (AC#3) — this proves responsiveness-based detection, not wall-clock. Verify the watchdog never calls `loop.set_debug`.

This task does NOT persist events to the DB — that wiring is T05. Emit the in-memory event/warning and expose enough structure (app_key, duration, tier, stack) for T05 to consume.

## Focus
- Build only on the mechanism T02 chose; do not re-litigate or keep both. If T02 chose the daemon thread, ensure it's a `daemon=True` thread torn down cleanly on shutdown.
- `src/hassette/core/core.py:444` `run_forever`: `_loop_thread_id` at 449, `set_task_factory` at 453, then `on_initialize()` and service starts. Install the watchdog in this method, after 449. The `HassetteHarness` (`src/hassette/test_utils/harness.py:534`) sets the task factory for tests — wire watchdog install so harness-based integration tests can exercise it (mirror how the harness brings up other components).
- **Slow-async vs blocking is the core correctness property (FR#9/AC#3).** An `await` yields to the loop, so the heartbeat/tick keeps advancing — no lag. Only a synchronous block starves it. Make the AC#3 test explicit and central.
- Reuse `is_internal_frame` from `src/hassette/utils/source_capture.py` to drop hassette frames from the severe-stall stack.
- Threshold/interval defaults live in `BlockingIODetectionConfig` (T01); confirm them against real timing during this task and update the design's Open Question on defaults if they change.
- Capture full test output to a tmp file per the command-output rule; do NOT run `pytest -n auto` (machine-freeze risk — see repo memory).

## Verify
- [ ] FR#1: The watchdog measures loop responsiveness continuously with no call to `loop.set_debug(True)` anywhere in the path (asserted by test/grep).
- [ ] FR#2: On a stall past threshold, it emits a signal naming the app, the handler/job, and the measured stall duration.
- [ ] FR#3: The watchdog is enabled by default (`watchdog_enabled=True`) and its default response is warn — a test confirms it never raises on a stall under default config.
- [ ] FR#9: A handler running `await asyncio.sleep(T)` for T past threshold produces no blocking warning.
- [ ] AC#1: A `time.sleep(T)` handler produces exactly one warning naming that app with duration ≈ T.
- [ ] AC#3: The `await asyncio.sleep(T)` case produces zero warnings (paired with FR#9, asserted in the same test module).

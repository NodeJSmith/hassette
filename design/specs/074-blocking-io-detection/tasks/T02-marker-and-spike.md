---
task_id: "T02"
title: "Add thread-visible execution marker and resolve watchdog mechanism"
status: "planned"
depends_on: ["T01"]
implements: ["FR#4", "AC#2"]
---

## Summary
Add a thread-visible "currently executing" marker to the command executor and resolve the make-or-break design question: which watchdog mechanism (in-loop `call_later` heartbeat vs. dedicated daemon thread) attributes a loop stall to the *correct* app. This is the spike the design defers — its deliverable is the marker (which stays) plus a recorded mechanism decision and a test proving correct attribution under the "next execution scheduled immediately after" condition. T03 builds the real watchdog on the chosen mechanism.

## Prompt
Resolve the attribution question flagged in `design/specs/074-blocking-io-detection/design.md`, `## Architecture` → "Tier 1", and `## Open Questions` (watchdog mechanism). Read the `## Key Constraints` and Convention Example "Per-execution context binding" first.

1. **Thread-visible marker** — add a plain attribute (NOT a ContextVar) on the command executor that records the currently-running execution as `(app_key, instance_name, execution_id, started_at)`. Set it in `bind_execution_context` (`src/hassette/core/command_executor.py:422`) on entry; clear it in `unbind_execution_context` (line 439, the paired teardown called from both `finally` blocks). Use a monotonic clock (`loop.time()` or equivalent) for `started_at`. The marker must be readable from another OS thread (a plain instance attribute or module-level holder — not a `ContextVar`, which is per-context and unreadable cross-thread). Reading a partially-written marker must be safe: store the marker as an immutable `NamedTuple` (or frozen dataclass) and publish it via a single attribute assignment — a rebinding that is atomic under the GIL — setting it to `None` when idle. Never mutate the marker in place.
2. **Spike both candidates** — prototype each enough to measure attribution correctness:
   - **Candidate A** — in-loop `loop.call_later` heartbeat measuring lag (actual vs expected fire time). Note: it runs only *after* the block clears, so it must read "the handle that just ran" — the marker plus its `started_at`/duration — not the live marker.
   - **Candidate B** — a dedicated daemon thread observing a thread-visible "last loop tick" timestamp plus the marker. It can read the marker *during* the block (the `finally` hasn't run yet) and snapshot `sys._current_frames()[loop_thread_id]` live.
3. **Pick the winner** — the deciding test: a handler calls `time.sleep(T)` (T past threshold), and *another* execution is scheduled to run immediately after. The chosen mechanism must attribute the stall to the app that called `time.sleep`, NOT the next execution (this is FR#4 / AC#2). Whichever candidate passes that test cleanly is the choice.
4. **Record the decision** — update the design doc's `## Architecture` → "Tier 1" and the `## Open Questions` "watchdog mechanism" entry with the chosen mechanism and why. Keep the marker code; discard the losing prototype (do not leave dead code — see the laziness protocol).
5. **Leave a test that pins attribution** — a regression test that fails if the marker is misattributed (the deciding test from step 3), so T03 inherits a green attribution guarantee.

## Focus
- `src/hassette/core/command_executor.py`: `bind_execution_context` (422) returns `(execution_id, token)`; `unbind_execution_context` (439) is a `@staticmethod` today — if the marker needs `self`, make it an instance method or store the marker on the executor instance and clear it from the instance. `execute_handler` `finally` is at 483, `execute_job` `finally` at 520; both call `unbind_execution_context(token)`.
- `bind_execution_context` has **no external callers** (grep confirms) — the change is contained to the executor. Do not alter the existing `CURRENT_EXECUTION_ID` / structlog lifecycle; the marker is purely additive.
- Sub-tasks spawned by handlers inherit a snapshot of `CURRENT_EXECUTION_ID` that is not cleared when the parent ends (`src/hassette/context.py:17` docstring). The marker must reflect what actually holds the loop thread, so blame stays correct even when spawned tasks linger.
- The loop thread id is `self._loop_thread_id` (captured `core.py:449`). For Candidate B, `sys._current_frames()` may not contain the loop thread id or may be empty — handle gracefully (omit the stack, keep the attribution).
- Loop policy is stdlib asyncio (`asyncio.run` in `cli/commands/run.py:45`) — no uvloop — but prefer loop-agnostic timing (`call_later` lag or wall-clock) regardless.
- Use the gate pattern from `CLAUDE.md` (Regression test patterns → Startup races) to drive deterministic timing in the test.

## Verify
- [ ] FR#4: The marker is set on execution entry and cleared on exit; a test shows the watchdog mechanism reads the execution that held the loop during a stall, not a later one.
- [ ] AC#2: With a blocking `time.sleep(T)` handler and another execution scheduled immediately after, the chosen mechanism attributes the stall to the `time.sleep` caller's app; the deciding test passes and is committed as a regression guard. The chosen mechanism is recorded in design.md.

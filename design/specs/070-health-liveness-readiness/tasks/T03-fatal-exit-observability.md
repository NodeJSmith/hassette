---
task_id: "T03"
title: "Make fatal self-shutdown exit non-zero and observable"
status: "planned"
depends_on: []
implements: ["FR#7", "FR#9", "AC#10", "AC#11", "AC#12"]
---

## Summary
Hassette already self-terminates on a fatal failure but exits `0` whether the shutdown was a clean SIGTERM or a fatal crash, so `systemd Restart=on-failure` can't react. Make a failure-driven shutdown exit non-zero (reusing the existing `FatalError → SystemExit(1)` path), emit a clear top-level log line naming the cause, and confirm the crash is persisted to the telemetry DB before exit. A clean operator shutdown still exits 0. The self-shutdown model itself is unchanged — this only makes it legible to external supervisors.

## Prompt
Implement the fatal-exit observability described in `design.md` → Architecture → "Shutdown model (decision) and fatal-exit observability".

1. **`src/hassette/core/core.py`** — add a `Hassette` field `self._fatal_shutdown_reason: str | None = None`. In `run_forever()` (~line 440), the two startup-failure branches that currently call `await self.shutdown()` then `return` — session-tracking init failure (~`:465`) and required services failing to start (~`:488`) — set `self._fatal_shutdown_reason` with a descriptive reason before tearing down. After the run loop's graceful teardown completes, if `self._fatal_shutdown_reason` is set, raise `FatalError(self._fatal_shutdown_reason)` instead of returning normally. Emit a top-level ERROR/CRITICAL log record naming the failing service and reason at that point, distinct from the existing "Hassette stopped." line.

2. **`src/hassette/core/service_watcher.py`** — `shutdown_if_crashed` (~line 449, subscribed to `CRASHED` at `:569`) is the universal reaction to a crash and calls `await self.hassette.shutdown()`. Set the `Hassette` fatal reason here (carrying the failing service name + exception from the event) before it tears down. This single site covers PERMANENT budget exhaustion and any fatal-error crash. Do NOT change the restart/budget decision logic (`restart_service`, `_handle_exhaustion`, the `RestartSpec` handling) — only add the fatal-reason signal.

3. **`src/hassette/core/session_manager.py`** — no new code expected: `on_service_crashed` (~`:93`, subscribed to `CRASHED` at `:52`) already sets the session error and `finalize_session` (~`:118`) preserves the failure status to the DB during teardown. Confirm this ordering holds under the fatal path (teardown runs before the non-zero exit) and add the test below.

4. **Contract for the exit path:** an operator SIGTERM goes through `request_shutdown` (`server.py:26` → `core.request_shutdown`), which leaves `_fatal_shutdown_reason` unset → `run_forever()` returns normally → `server.main` returns → `run.py:45` `asyncio.run(...)` completes → exit `0`. A fatal shutdown sets the reason → `run_forever()` raises `FatalError` → `run.py:52`'s existing `except FatalError → SystemExit(1)` handles it. Confirm and wire the resumption path: how `run_forever()`'s `shutdown_event.wait()` (`core.py:506`) unblocks after `shutdown_if_crashed` runs in a bus-handler task. The contract is "fatal reason set ⇒ non-zero exit, after graceful teardown"; pick the wiring that satisfies it (e.g. have `shutdown_if_crashed` also request the run loop to unblock).

5. **Tests** — per `design.md` → Test Strategy. Assert on exit code and the persisted telemetry row, NEVER on log output (project rule: no log-capture tests):
   - A failure-driven shutdown (drive a PERMANENT service to its exhaustion path so the watcher emits `CRASHED` → `shutdown_if_crashed`) causes the entry path to exit non-zero / `run_forever()` to raise `FatalError`.
   - A SIGTERM/operator shutdown (`request_shutdown`) exits 0.
   - After a `CRASHED` event for a PERMANENT service, the active session row in the telemetry DB carries the failure status, written before teardown completes. NOTE: `on_service_crashed` submits the session error to the async database write queue (`_database_service.submit`); assert on the persisted row only after the session is fully finalized (teardown/`finalize_session` complete), not immediately after the `CRASHED` event fires, or the write may not have drained yet.

## Focus
- Exit path: `__main__:entrypoint` → `cli/commands/run.py:45` `asyncio.run(run_server(config))` (inside a `try` with `except FatalError → SystemExit(1)` at `:52`) → `server.py:30` `await core.run_forever()`.
- `CRASHED` is always terminal: recoverable failures emit `FAILED` (handled by `restart_service`, `service_watcher.py:563`); only `CRASHED` reaches `shutdown_if_crashed`. So a TRANSIENT service bouncing within budget never triggers a fatal exit — only true exhaustion (PERMANENT) or a `fatal_error_name` (any type) does. Exhaustion of a non-critical TRANSIENT/TEMPORARY service sets `EXHAUSTED_DEAD`, not `CRASHED`, and must NOT exit the process.
- The inline `shutdown()` calls at `service_watcher.py:196` (PERMANENT exhaustion) and `:352` (fatal error) are redundant with `shutdown_if_crashed` (idempotent). Set the fatal reason in the one reactive handler, not at the inline sites, to avoid two sources of truth.
- `shutdown()` (`core.py:566`) is wrapped in a total-timeout and is idempotent (`shutdown_completed`/`shutting_down` guards). `before_shutdown` (`:599`) calls `finalize_session` — this is where the crash record is preserved.
- `request_shutdown` (`mixins.py:235`) sets `shutdown_event` (`mixins.py:239`) and is the clean/operator path (SIGTERM handler at `server.py:26`).
- IMPORTANT wiring fact: `shutdown()` (`core.py:566`) does NOT set `shutdown_event` — only `request_shutdown` does. So `shutdown_if_crashed` calling `shutdown()` directly does not unblock `run_forever()`'s `shutdown_event.wait()` (`core.py:506`); today that resume likely happens via task cancellation (`except asyncio.CancelledError` at `:507`). The cleanest fatal wiring is therefore to route the crash path through `request_shutdown(reason)` (setting the fatal reason + `shutdown_event` together) rather than a bare `shutdown()`, so `run_forever()` unblocks deterministically and can then raise `FatalError`. Confirm the actual resume mechanism before choosing.

## Verify
- [ ] FR#7: A failure-driven shutdown (PERMANENT exhaustion / fatal error / startup failure) results in a non-zero process exit; an operator SIGTERM results in exit 0.
- [ ] FR#9: After a fatal service crash, the active session row in the telemetry DB carries the failure status, written before shutdown completes (assert on the persisted row, not logs).
- [ ] AC#10: A fatal shutdown (a PERMANENT service exhausting its budget) causes a non-zero process exit code.
- [ ] AC#11: An operator/SIGTERM shutdown causes exit code 0.
- [ ] AC#12: After a fatal crash, the session row in the telemetry DB carries the failure status, written before shutdown completes.

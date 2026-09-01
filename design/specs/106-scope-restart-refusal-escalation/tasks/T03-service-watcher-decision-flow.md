---
task_id: "T03"
title: "Wire confirmed-quiescence gating into ServiceWatcher's restart-refusal handling"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#3", "FR#4", "FR#5", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7"]
---

## Target Files

- modify: `src/hassette/core/service_watcher.py`
- modify: `src/hassette/resources/restart.py`
- modify: `src/hassette/core/websocket_service.py`
- create: `tests/integration/test_service_watcher_refusal_scoping.py`

## Prompt

Read the design doc's "Wait, then decide" and "Why `PERMANENT` services and `WebsocketService` are excluded" subsections under `## Approach` (`design/specs/106-scope-restart-refusal-escalation/design.md`) for full rationale, and the "Test placement" subsection for why new integration tests go in a new file rather than the existing `tests/integration/test_service_watcher.py`.

### `src/hassette/resources/restart.py`

Add a new field to `RestartSpec`:

```python
degrade_on_confirmed_quiescent_refusal: bool = True
"""Whether a timeout-only restart refusal, once confirmed quiescent, degrades just this service
to EXHAUSTED_DEAD instead of escalating to root shutdown. False for services where running the
rest of the framework without this one is worse than a clean restart."""
```

Set `degrade_on_confirmed_quiescent_refusal=False` explicitly on `CORE_PERMANENT_RESTART` — this covers `BusService`, `SchedulerService`, and `SyncExecutorService` in one place, since all three already use this shared constant.

### `src/hassette/core/websocket_service.py`

Add `degrade_on_confirmed_quiescent_refusal=False` to `WebsocketService.restart_spec`'s existing `RestartSpec(restart_type=RestartType.TRANSIENT, ...)` call. `WebsocketService` stays `TRANSIENT` (it still needs ordinary budget/backoff/cooldown behavior for ordinary restart failures) — only this one new field opts it out of the confirmed-quiescent degrade path, because it's the framework's sole connection to Home Assistant and degrading it silently would leave Hassette running with no path back to HA for the rest of the process's life.

This task depends on T01 (`TeardownReport.is_timeout_only_refusal`, in `src/hassette/resources/teardown.py`) and T02 (`is_teardown_confirmed_quiescent`, in `src/hassette/resources/lifecycle.py`; also T02 adds `EXHAUSTED_DEAD` to `VALID_TRANSITIONS[ResourceStatus.STOPPED]` in `src/hassette/resources/mixins.py`, which this task's `set_service_status(..., EXHAUSTED_DEAD)` call below depends on) — all of T02's changes must already exist.

**Bystander guard note:** `already_shutting_down` is captured *before* the confirmation wait begins, specifically so the escalation branch can tell "this service's own refusal caused the shutdown" apart from "shutdown was already in progress for an unrelated reason when this wait aborted." When it's the latter, skip the `handle_restart_refused()` call entirely rather than dispatching a second, misattributed `CRASHED` event for a service that wasn't the actual cause.

**Diagnostic payload note:** the confirmed-dead event uses `HassetteServiceEvent.from_service_status(..., exception=error)` (already imported at the top of this file), not `self.emit_service_status_event(...)` — the latter only pulls exception fields from an existing `ServiceStatusPayload` passed as `source_payload`, which doesn't apply here (there's no prior event to extract one from, only the `RestartRefusedError`). `from_service_status()` accepts an `exception` directly, matching the exact pattern `handle_restart_refused()` already uses for its own `CRASHED` event (`service_watcher.py:248-255`). Without this, the emitted event carries no exception/traceback and the dashboard's exception-disclosure UI never renders for this path.

**Status transition note:** `previous_status=service.status` (not a hardcoded `ResourceStatus.FAILED`) below is deliberate — by the time this method runs, `service.shutdown()` has already completed and driven the resource to `STOPPED` (never `FAILED`), regardless of whether the resulting `TeardownReport` was safe. Passing the real current status keeps the emitted event accurate and relies on T02's `VALID_TRANSITIONS` addition to make the `STOPPED -> EXHAUSTED_DEAD` transition valid.

### In `src/hassette/core/service_watcher.py`

1. Add `is_teardown_confirmed_quiescent` to the existing `from hassette.resources.lifecycle import ...` import line.

2. Add a module-level constant near the existing `SERVICE_STATUS_PATH` constant:

   ```python
   _DEATH_CONFIRMATION_POLL_SECONDS = 1.0
   """Poll interval while waiting to confirm a timeout-only refusal's tracked tasks have died."""
   ```

3. Add two new async methods on `ServiceWatcher` (place them near `handle_restart_refused`, since they form one decision flow):

   ```python
   async def wait_for_teardown_confirmation(self, service: Service, timeout: float) -> bool:
       """Poll until the service's last teardown attempt is confirmed quiescent, or timeout elapses.

       Returns True if confirmed quiescent within the timeout, False if the timeout elapsed
       first or shutdown was requested mid-wait.
       """
       deadline = time.monotonic() + timeout
       while True:
           if is_teardown_confirmed_quiescent(service):
               return True
           remaining = deadline - time.monotonic()
           if remaining <= 0:
               return False
           completed = await self.shutdown_safe_sleep(min(_DEATH_CONFIRMATION_POLL_SECONDS, remaining))
           if not completed:
               return False

   async def handle_timeout_only_refusal(
       self, name: str, role: object, service: Service, error: RestartRefusedError
   ) -> None:
       """Wait for confirmed quiescence after a timeout-only refusal, then degrade just this
       service instead of escalating -- or escalate exactly as handle_restart_refused would if
       quiescence is never confirmed within the wait.
       """
       # Recorded before the wait so we can tell "this service caused the shutdown" apart from
       # "shutdown was already happening for an unrelated reason when this wait aborted."
       already_shutting_down = self.hassette.shutdown_event.is_set()
       # Half the original teardown timeout: that timeout already fired once discovering this
       # resource wouldn't die cleanly, so reusing the full value here would let a genuinely-stuck
       # resource take up to 2x as long to reach root shutdown.
       timeout = self.hassette.config.lifecycle.resource_shutdown_timeout_seconds / 2
       if await self.wait_for_teardown_confirmation(service, timeout):
           self.logger.warning(
               "%s '%s' restart refused (timeout-only: %s), confirmed no tasks still running -- "
               "marking EXHAUSTED_DEAD instead of shutting down the process",
               role,
               name,
               ", ".join(error.report.causes),
           )
           dead_event = HassetteServiceEvent.from_service_status(
               resource_name=name,
               role=role,  # pyright: ignore[reportArgumentType]
               status=ResourceStatus.EXHAUSTED_DEAD,
               previous_status=service.status,
               exception=error,
           )
           await self.hassette.send_event(dead_event)
           self.set_service_status(name, role, ResourceStatus.EXHAUSTED_DEAD)
           return
       if already_shutting_down:
           self.logger.warning(
               "%s '%s' restart refused (timeout-only: %s) during an already-in-progress "
               "shutdown for an unrelated reason -- skipping a redundant, misattributed CRASHED "
               "event for this service",
               role,
               name,
               ", ".join(error.report.causes),
           )
           return
       self.logger.warning(
           "%s '%s' restart refused (timeout-only: %s) but could not confirm quiescence within "
           "%.1fs -- escalating",
           role,
           name,
           ", ".join(error.report.causes),
           timeout,
       )
       await self.handle_restart_refused(name, role, error)
   ```

4. In `cooldown_and_retry()`, change the existing block:

   ```python
   except RestartRefusedError as exc:
       await self.handle_restart_refused(name, role, exc)
   ```

   to:

   ```python
   except RestartRefusedError as exc:
       if exc.report.is_timeout_only_refusal and spec.degrade_on_confirmed_quiescent_refusal:
           await self.handle_timeout_only_refusal(name, role, service, exc)
       else:
           await self.handle_restart_refused(name, role, exc)
   ```

   `service` and `spec` are already in scope in `cooldown_and_retry` (the `service` local is resolved via `get_service()` a few lines above; `spec` is the method's parameter).

5. In `execute_restart()`, apply the identical change to its own `except RestartRefusedError as exc:` block. `service` and `spec` are already method parameters there.

### New file `tests/integration/test_service_watcher_refusal_scoping.py`

Follow the existing conventions in `tests/integration/test_service_watcher.py` and `tests/unit/core/test_service_watcher_exhausted.py` (read both first) for fixture setup, harness usage, and how a `RestartRefusedError` / `TeardownReport` is simulated for a test service. Use the event-gated timing pattern from `CLAUDE.md`'s "Regression test patterns for this project" — never `asyncio.sleep(0)` to fake timing.

Write these tests:

1. **Unconfirmed-death still escalates (AC#3).** A `TRANSIENT`-restart-type test service's `restart()` raises `RestartRefusedError` with a timeout-only `TeardownReport` (e.g. `TASKS_PENDING`), and its `task_bucket` has a task that never completes within the confirmation wait (control this with a low `resource_shutdown_timeout_seconds` config override so the test runs fast, and an `asyncio.Event` that the test never sets). Assert `hassette.fatal_shutdown_reason` is set and `hassette.shutdown_event` is set afterward — the unchanged root-shutdown outcome.

2. **Confirmed death degrades just that service (AC#4).** Same setup, but the test releases the pending task's gating event shortly after the confirmation wait begins — well within `resource_shutdown_timeout_seconds / 2` (the actual wait bound; do not confuse this with the full `resource_shutdown_timeout_seconds` value, which only bounds the *original* teardown attempt, not this confirmation wait). Assert the failing service ends at `ResourceStatus.EXHAUSTED_DEAD`, a sibling service in the same harness remains `ResourceStatus.RUNNING`, and `hassette.fatal_shutdown_reason` is `None` / `shutdown_event` is not set.

3. **`PERMANENT` still escalates even when confirmed dead (AC#5).** Same confirmed-death setup as test 2, but the failing service uses `restart_spec = CORE_PERMANENT_RESTART`. Do **not** substitute a bare `RestartSpec(restart_type=RestartType.PERMANENT)` — the escalation guard checks `degrade_on_confirmed_quiescent_refusal`, not `restart_type` (they're deliberately decoupled; see design.md's "Why `PERMANENT` services and `WebsocketService` are excluded"), and a bare `RestartSpec(restart_type=RestartType.PERMANENT)` leaves `degrade_on_confirmed_quiescent_refusal` at its default `True`, which would make this test actually take the confirmed-quiescent degrade path and land at `EXHAUSTED_DEAD` — the opposite of what this test must prove. Use `CORE_PERMANENT_RESTART` itself, or an explicit `RestartSpec(restart_type=RestartType.PERMANENT, degrade_on_confirmed_quiescent_refusal=False)` if a fresh instance is needed. Assert it still results in root shutdown (fatal reason + shutdown_event set), not `EXHAUSTED_DEAD`.

4. **`WebsocketService` still escalates even when confirmed dead (AC#7).** First, a small unit-level assertion (can live in this file or wherever's most natural): `WebsocketService.restart_spec.degrade_on_confirmed_quiescent_refusal is False`. Then the same confirmed-death integration setup as test 2, but using an actual `WebsocketService` instance (`TRANSIENT`, not `PERMANENT`) as the failing service. Assert it still results in root shutdown (fatal reason + shutdown_event set), not `EXHAUSTED_DEAD` — proving the opt-out field, not `restart_type`, is what the guard actually checks.

5. **Bystander guard skips the redundant CRASHED event.** Set `hassette.shutdown_event` before triggering the refused restart (simulating an unrelated fatal failure already in progress elsewhere), using a `TRANSIENT` test service whose timeout-only refusal never confirms quiescent within the wait (same non-confirming setup as test 1). Assert `handle_timeout_only_refusal()` returns without calling `handle_restart_refused()` — e.g. by spying on/patching `handle_restart_refused` and asserting it was never called, or by asserting no *additional* `CRASHED` event was dispatched for this service beyond whatever the unrelated pre-existing shutdown already produced. This exercises the `already_shutting_down` branch added to fix Finding 9 of the sketch-time challenge, which otherwise has no test coverage anywhere in this task.

## Verify

- [ ] FR#3: Timeout-only refusals for `TRANSIENT`/`TEMPORARY` services with `degrade_on_confirmed_quiescent_refusal=True` wait up to half of `resource_shutdown_timeout_seconds` for confirmed quiescence before deciding.
- [ ] FR#4: Confirmed-quiescent within the wait results in only that service reaching `EXHAUSTED_DEAD`; no fatal reason recorded, no root shutdown.
- [ ] FR#5: Unconfirmed quiescence, a non-timeout-only cause, or a service with `degrade_on_confirmed_quiescent_refusal=False` (`PERMANENT` services and `WebsocketService`) all fall back to today's unchanged root-shutdown escalation.
- [ ] AC#3, AC#4, AC#5, AC#7: `uv run pytest tests/integration/test_service_watcher_refusal_scoping.py -v` passes with all four scenarios above.
- [ ] Bystander guard: test 5 above passes — a timeout-only refusal that never confirms quiescent during an already-in-progress unrelated shutdown does not trigger a redundant `handle_restart_refused()` call or a second misattributed `CRASHED` event.
- [ ] AC#6: `prek -a` passes; `uv run pytest tests/unit/resources/test_teardown.py tests/unit/resources/lifecycle/test_shutdown.py tests/integration/test_service_watcher_refusal_scoping.py tests/integration/test_service_watcher.py tests/unit/core/test_service_watcher_coverage.py tests/unit/core/test_service_watcher_exhausted.py -v` passes (existing service_watcher suites unaffected).

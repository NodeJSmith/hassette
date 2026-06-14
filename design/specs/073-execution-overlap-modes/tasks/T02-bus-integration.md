---
task_id: "T02"
title: "Wire mode into bus registration, dispatch, and tier default"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#12", "FR#17", "FR#20", "FR#21", "FR#22", "AC#2", "AC#3", "AC#4", "AC#6", "AC#7", "AC#8", "AC#9", "AC#14", "AC#15", "AC#16"]
---

## Summary

Thread the `mode` parameter through the bus: add it to `ListenerOptions` and the `Options` TypedDict, compute the tier-aware default at registration, give each `HandlerInvoker` an `ExecutionModeGuard`, and wrap the dispatch chokepoint with it while keeping the handler task visible to `_dispatch_pending`. Release the guard on listener cancellation. Add integration tests for every mode through real registrations, the tier default, composition with debounce/once/duration, and a framework-tier no-regression check. Also add the stall WARNING for a handler holding a `single`/`queued` guard too long.

## Prompt

All paths under `src/hassette/`. Reuse the `ExecutionMode` enum and `ExecutionModeGuard` from T01.

1. **`ListenerOptions`** (`bus/listeners.py:67`): add `mode: ExecutionMode = ExecutionMode.SINGLE`. The enum coercion is the validation (an invalid string fails coercion — FR#12); add an explicit `__post_init__` coercion/check only if the field can arrive as a raw `str` (it can, via the `Options` TypedDict and the scheduler-style `str` ergonomics), so coerce `str → ExecutionMode` and raise a clear `ValueError` on an unknown value.

2. **`Options` TypedDict + the explicit-signature methods** (`bus/options.py`, `bus/bus.py`, `bus/sync.py`): add `mode: ExecutionMode | str` to the `Options` TypedDict. The three **typed convenience methods** (`on_state_change`, `on_attribute_change`, `on_call_service`) pass `**opts: Unpack[Options]` in both the async (`bus.py`) and sync (`bus/sync.py`) classes, so they pick up `mode` for free — confirm this. **BUT the generic `on()` method has an explicit hand-written signature (no `**opts`) in both `bus.py:429` (async) and `bus/sync.py:88` (sync), and the shared `_on_internal` at `bus.py:514` is also explicit** — you must add a `mode` keyword parameter to all three of those signatures manually and thread it through (`on` → `_on_internal` → `ListenerOptions`), or `on(..., mode=...)` will be rejected and FR#2 is only partially met. Update the relevant docstrings to mention `mode`.

3. **Tier-aware default** (`bus.py` around line 552, where `source_tier = parent.source_tier` is resolved and asserted): when `mode` was not explicitly supplied, default it to `ExecutionMode.PARALLEL` for `source_tier == "framework"` and `ExecutionMode.SINGLE` otherwise (FR#3). An explicit `mode=` always wins. Apply this before `ListenerOptions` is constructed (the options builder at `bus.py:573`). Distinguish "not supplied" from "supplied as single" — e.g. default the `Options`/parameter to a sentinel (`None`) and resolve to the tier default when absent, so a framework listener that passes no mode gets `parallel`, not `single`.

4. **Guard ownership + dispatch wrap** (`bus/listeners.py`): `HandlerInvoker` owns an `ExecutionModeGuard` built from the resolved `options.mode`. Wrap the innermost run in `HandlerInvoker.dispatch()` (line 192) so the order is once-guard → rate limiter (`self.rate_limiter.call`) → mode guard → `invoke_fn`.

   **Important — there is no existing cancellable per-handler task to reuse.** Today `BusService.dispatch` spawns one task per (event, listener) at `core/bus_service.py:324`, and `_dispatch` (`bus_service.py:384`) `await`s `invoke_fn()` *inline* inside that task — the handler is not its own task. For `restart`/`single`/`queued` the guard needs a cancellable handle, so the "run-and-track" callable you pass it must spawn a **new child task** for the invocation (via the same `task_bucket` the bus uses) and return it; the guard retains that child task and `await`s it. The outer per-dispatch task stays pending while the child runs, so `_dispatch_pending` accounting remains correct via the outer task — do NOT detach the child from `task_bucket`. When `restart` cancels the child, swallow the resulting `CancelledError` at the guard so the outer dispatch task does not crash. For `parallel`, the guard is a pass-through that `await`s `invoke_fn()` inline exactly as today (no child task) — byte-for-byte unchanged. On `Suppressed`/`Dropped` outcomes the counters live on the guard (read by T03); nothing is written to the DB here.

5. **Release on cancel** (`bus/listeners.py` `Listener.cancel`/`HandlerInvoker`, and `core/bus_service.py` `remove_listener`): call the guard's `release()` when a listener is cancelled or replaced so in-flight tasks and queued factories are dropped with no leaked references (FR#17).

6. **Stall WARNING** (observability): when an invocation holds a `single`/`queued` guard longer than a threshold (independent of the per-listener `timeout`, which still ultimately releases it via `command_executor`), emit a WARNING naming the listener. This is the ONLY WARNING in this feature — suppression/drops stay DEBUG. Keep the threshold a module constant.

7. **Integration tests** (`tests/integration/` and `tests/unit/`):
   - Each mode through a real `self.bus.on_state_change(...)` registration: `single` exactly-one + DEBUG (AC#3), `restart` cancels+reruns without crashing the bucket (AC#4), `queued` orders (AC#6), `queued` cap drops newest (AC#7), `parallel` concurrent (AC#8). Use the `HassetteHarness` integration fixtures (see `tests/TESTING.md`).
   - Tier default: extend `tests/unit/test_source_tier_propagation.py` — app-tier registration without `mode` resolves to `single`, framework-tier to `parallel` (AC#2).
   - Invalid `mode` raises at registration (AC#9).
   - Composition: `mode="single"` + `debounce` (AC#14, FR#20); `once=True` + a non-`single` mode fires at most once (AC#15, FR#21); duration-hold + `mode="single"` applies the guard at hold-expiry dispatch, not trigger arrival (AC#16, FR#22).
   - Framework-tier no-regression: a system/integration assertion that a framework listener registered without `mode` still processes concurrent events (the supervisor restarting a second failed service while a first restart is in backoff — see `core/service_watcher.py`). This guards the critical finding that the tier default must not constrain framework listeners.

Run the affected test files and confirm they pass before finishing. Because this touches `core/bus_service.py` dispatch, also run `uv run nox -s system` per CLAUDE.md.

## Focus

- Chokepoint is `HandlerInvoker.dispatch` at `bus/listeners.py:192`; the dispatch task is spawned by `BusService.dispatch` at `core/bus_service.py:325`; `_dispatch_pending` is the drain counter the guard's task must remain visible to — do NOT spawn a detached task.
- `bus/sync.py` mirrors the async methods via `**opts: Unpack[Options]` at lines ~88/160/223/284 — adding `mode` to `Options` covers the sync facade with no signature edit. Verify, don't rewrite.
- `ListenerOptions` is constructed keyword-only at `bus.py:573`, `bus/listeners.py:488`, and `test_utils/helpers.py:509` — a keyword field with a default is safe; spot-check these three after the change.
- Duration-hold dispatches via `listener.invoker.dispatch` (`bus/duration_hold.py:144,166,224`), so the guard already applies at hold-expiry through the same chokepoint — verify, and add the composition test.
- `once` excludes debounce/throttle (existing `__post_init__` rule); `mode` does not, so `once` + any mode is allowed and the once-guard runs before the mode guard.
- Config-drift tracking lives in `config_matches()` (`bus/listeners.py:360`) and `diff_fields()` (`:386`) — add `mode` to BOTH so a mode-only re-registration is a detected diff. Do NOT touch `matches()` (`:418`): that is the **event-predicate** matcher (decides whether an event fires the handler), unrelated to config drift — editing it would break event matching.
- Keep `parallel` a true no-op path; the riskiest regression is silently changing framework-listener behavior — the no-regression test is the guard against it.
- `python.md`: no future annotations, `X | None`, top-level imports.

## Verify
- [ ] FR#2: all four async bus methods and the `bus/sync.py` sync facades accept `mode=` (via the `Options` TypedDict).
- [ ] FR#3: an app-tier registration without `mode` resolves to `single`; a framework-tier one resolves to `parallel`.
- [ ] FR#12: passing an invalid `mode` string raises a clear error at registration time.
- [ ] FR#17: cancelling/replacing a listener calls the guard's `release()`; no in-flight task or queued factory leaks.
- [ ] FR#20: a handler with `debounce` + `mode="single"` debounces starts and suppresses overlap among started invocations.
- [ ] FR#21: a `once=True` handler fires at most once regardless of mode.
- [ ] FR#22: a duration-hold handler applies the guard at hold-expiry dispatch, not trigger arrival.
- [ ] AC#2: test shows app→`single`, framework→`parallel` defaults.
- [ ] AC#3: integration test — `single` yields exactly one execution on a double-fire, with a DEBUG drop.
- [ ] AC#4: integration test — `restart` cancels the first and runs the second; the dispatching bucket does not error.
- [ ] AC#6: integration test — `queued` runs N triggers in order.
- [ ] AC#7: integration test — `queued` at cap drops newest, runs the rest, counts the drop.
- [ ] AC#8: integration test — `parallel` runs M triggers concurrently.
- [ ] AC#9: integration test — invalid `mode` raises at registration.
- [ ] AC#14: integration test — `debounce` + `mode="single"` compose correctly.
- [ ] AC#15: integration test — `once=True` fires at most once in any mode.
- [ ] AC#16: integration test — duration-hold + `mode="single"` guards at hold-expiry.

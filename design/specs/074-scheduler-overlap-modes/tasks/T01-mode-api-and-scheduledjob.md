---
task_id: "T01"
title: "Add mode parameter, resolution, and guard to scheduler API"
status: "done"
depends_on: []
implements: ["FR#4", "FR#6", "FR#7", "FR#8", "FR#9", "AC#2", "AC#8", "AC#9"]
---

## Summary

Establish the public-API and data-shape layer for scheduler overlap modes. Add a `mode` parameter
to `Scheduler.schedule()` and all seven convenience methods plus the sync facade, resolve it
tier-aware (app→`single`, framework→`parallel`) with string coercion and validation, and store the
resolved `ExecutionMode` plus a per-job `ExecutionModeGuard` on `ScheduledJob`. This task does NOT
change dispatch behavior (T02) or persistence (T03) — it only makes mode accepted, validated, and
carried on the job object with its guard.

## Prompt

Implement the mode-acceptance and guard-ownership layer. Follow design.md sections
"Architecture §2 (The guard lives on ScheduledJob)" and "Architecture §4 (Tier-aware mode
resolution)", and the "Tier-aware mode resolution" Convention Example in context.md.

1. **`src/hassette/scheduler/classes.py` — `ScheduledJob`:**
   - Add two `field(compare=False)` fields: `mode: ExecutionMode` and `guard: ExecutionModeGuard`
     (the latter `init=False`). `compare=False` is mandatory — `@dataclass(order=True)` must not
     include them in heap ordering.
   - In `__post_init__`, create the guard from the mode: `self.guard = ExecutionModeGuard(self.mode)`.
   - Add the import `from hassette.execution_mode import ExecutionModeGuard` and
     `from hassette.types.enums import ExecutionMode` (classes.py imports neither today).
   - Decide a safe default for the `mode` field so existing direct `ScheduledJob(...)` constructions
     in tests don't break — `mode: ExecutionMode = field(default=ExecutionMode.SINGLE, compare=False)`.
     The real resolution happens in `schedule()`.

2. **`src/hassette/scheduler/scheduler.py` — `Scheduler.schedule()`:**
   - Add `mode: "ExecutionMode | str | None" = None` (keyword-only, alongside `on_error`/`if_exists`).
   - Resolve it exactly as `bus.py:567-580` does (see Convention Example): `None` →
     `ExecutionMode.PARALLEL` if `source_tier == "framework"` else `ExecutionMode.SINGLE`; an
     `ExecutionMode` passes through; a string is coerced via `ExecutionMode(mode)`, raising
     `ValueError` naming the valid values on failure. The `source_tier` is already resolved in
     `schedule()` (line ~424).
   - Pass `mode=resolved_mode` to the `ScheduledJob(...)` constructor.
   - Import `ExecutionMode` from `hassette.types.enums`.

3. **The seven convenience methods** (`run_in`, `run_once`, `run_every`, `run_minutely`,
   `run_hourly`, `run_daily`, `run_cron` in `scheduler.py`): add the same
   `mode: "ExecutionMode | str | None" = None` keyword-only parameter and forward it to
   `self.schedule(..., mode=mode)`. Update each docstring's Args block briefly (the four modes, the
   tier-aware default, no-op on one-shots for `run_in`/`run_once`).

4. **`src/hassette/scheduler/sync.py` — `SchedulerSyncFacade`** (GAP from reverse-dep check): the
   facade wraps `schedule` and the seven convenience methods (lines ~79, 144, 197, 257, 316, 369,
   422, 523). Add the `mode` parameter to each wrapper and forward it, mirroring how `timeout`/
   `on_error` are threaded.

5. **Unit tests** (same task — co-located): test tier-aware resolution (app→single,
   framework→parallel), explicit mode passthrough, string coercion, invalid-string `ValueError`,
   and that `run_in`/`run_once` accept `mode=` and the resulting job still fires once (no-op). Place
   alongside existing scheduler unit tests (see Focus for location).

Do NOT touch `dispatch_and_log`, `reschedule_job`, persistence, or the web layer — those are T02/T03/T05.

## Focus

- `ScheduledJob` is `@dataclass(order=True)` (`classes.py:135`) — every new field MUST be
  `compare=False` or it corrupts heap ordering (`sort_index` is the only compare field). The
  `error_handler` field's comment (`classes.py:199-206`) explains this exact hazard — follow it.
- `__post_init__` is at `classes.py:242`; it already validates `timeout` and calls `set_next_run`.
  Add guard creation there. `ExecutionModeGuard.__init__` does no I/O and cannot fail.
- Mode resolution reference: `src/hassette/bus/bus.py:567-580` (copy the structure exactly,
  including the `ValueError` message format). `ExecutionMode`/`Outcome` live in
  `src/hassette/types/enums.py` (`ExecutionMode` at line 31, values `single`/`restart`/`queued`/
  `parallel`).
- `schedule()` already resolves `source_tier` (`scheduler.py:423-424`) and asserts it is
  `app`/`framework` — reuse that value for the tier-aware default.
- The sync facade (`scheduler/sync.py`) mirrors each async method; match the existing parameter
  ordering and the `run_sync`/delegation pattern already there.
- Existing scheduler unit tests: look under `tests/unit/core/` (e.g.
  `test_scheduler_service_dequeue.py`) and `tests/integration/test_scheduler.py`. Match the
  fixture/harness style (`HassetteHarness` for integration; see `tests/TESTING.md`).
- `ListenerOptions.__post_init__` (`bus/listeners.py:110-118`) shows the string→enum coercion
  pattern with the same `ValueError` message — mirror it.

## Verify

- [ ] FR#4: each `ScheduledJob` has an `ExecutionModeGuard` created in `__post_init__` from its `mode`; both fields are `compare=False`.
- [ ] FR#6: `schedule()` and all seven convenience methods (and their sync-facade wrappers) accept a `mode` keyword parameter.
- [ ] FR#7: an omitted mode resolves to `single` for an app-tier owner and `parallel` for a framework-tier owner.
- [ ] FR#8: an invalid mode string raises `ValueError` at scheduling time naming the valid values.
- [ ] FR#9: `mode=` is accepted on `run_in`/`run_once` without error.
- [ ] AC#2: a one-shot scheduled with `mode=` still fires exactly once (mode has no overlap effect).
- [ ] AC#8: omitted mode → `single` (app) / `parallel` (framework), asserted via the resolved `job.mode`.
- [ ] AC#9: invalid mode string raises `ValueError` naming valid values.

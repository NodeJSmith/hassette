---
task_id: "T02"
title: "Add where= parameter to Scheduler API with normalization and arity detection"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#9", "FR#10", "FR#16", "AC#5", "AC#6", "AC#10"]
---

## Summary
Thread the `where=` parameter through `Scheduler.schedule()` and all seven convenience methods. Implement predicate normalization (single callable stored directly, sequences collapsed into a closure) and arity detection (inspect signature once at registration, store `_predicate_wants_job` flag on the job). Validate that async predicates and predicates with >1 required positional or required keyword-only parameters raise `TypeError` at registration time. Unit tests for normalization, arity detection, and parameter forwarding.

## Target Files
- modify: `src/hassette/scheduler/scheduler.py`
- read: `src/hassette/scheduler/classes.py` (ScheduledJob fields from T01)
- read: `src/hassette/types/types.py` (SchedulerPredicate type from T01)
- read: `src/hassette/event_handling/predicates.py` (reference for normalization pattern)
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py`
- read: `design/specs/003-scheduler-where-predicates/design.md`

## Prompt
Add `where=` parameter support to the Scheduler's public API:

**1. `src/hassette/scheduler/scheduler.py` — `schedule()` method (line 360):**
- Add `where: "SchedulerPredicate | Sequence[SchedulerPredicate] | None" = None` parameter. Place it as a keyword-only argument after the existing `kwargs` parameter.
- After the existing validation block but before `add_job()`, add predicate normalization and arity inspection:

  **Normalization:**
  - If `where` is `None`, set `predicate = None` and `wants_job = False`.
  - If `where` is a `Sequence` (but not a string/bytes/callable), collapse into a closure: `preds = tuple(where); predicate = lambda: all(p() for p in preds)` and `wants_job = False`.
  - Otherwise (single callable), store directly: `predicate = where`.

  **Arity detection (for single callables only — closures are always zero-arg):**
  - Check `asyncio.iscoroutinefunction(predicate)` → raise `TypeError("Scheduler predicates must be synchronous")`.
  - Use `inspect.signature(predicate)` to count positional parameters (excluding `self` for bound methods).
  - >1 required positional → `TypeError`.
  - Any required keyword-only parameters → `TypeError`.
  - Exactly 1 positional parameter (required or optional) → `wants_job = True`.
  - Otherwise → `wants_job = False`.

  Set `job.predicate = predicate` and `job._predicate_wants_job = wants_job` on the constructed `ScheduledJob` before passing it to `add_job()`.

**2. `src/hassette/scheduler/scheduler.py` — convenience methods:**
- Add `where: "SchedulerPredicate | Sequence[SchedulerPredicate] | None" = None` to each: `run_in` (line 479), `run_once` (line 539), `run_every` (line 605), `run_minutely` (line 669), `run_hourly` (line 731), `run_daily` (line 793), `run_cron` (line 856).
- Each forwards `where=where` to `self.schedule(...)`.

**3. Tests:**
- Test arity detection: zero-arg callable → `_predicate_wants_job=False`, one-arg → `True`, >1 required positional → `TypeError`, required keyword-only → `TypeError`, async callable → `TypeError`.
- Test sequence normalization: `where=[pred1, pred2]` produces a single zero-arg callable that ANDs the results.
- Test parameter forwarding: verify each convenience method passes `where=` through to `schedule()` (mock `schedule()` and check kwargs).

See `## Architecture > Predicate arity detection` and `## Architecture > API surface` in the design doc.

## Focus
- Use `collections.abc.Sequence` for the isinstance check, not `typing.Sequence`. Check how the bus does it — `bus.py` line 693 checks `callable(where)` first.
- For arity detection, `inspect.signature()` can raise `ValueError` for builtins without a Python signature. Catch that and default to zero-arg (fail-safe — the predicate will just be called with no args; if it needs one, it'll get a runtime error).
- The closure collapse `lambda: all(p() for p in preds)` must capture `preds` as a tuple (not a list reference that could be mutated).
- `run_minutely` and `run_hourly` are thin wrappers around `run_every` — they should forward `where=` to `run_every`, not directly to `schedule()`.
- All convenience methods use keyword-only args after `*` — `where` should follow the same convention.

## Verify
- [ ] FR#1: `Scheduler.schedule()` accepts `where` parameter of the correct type
- [ ] FR#2: All seven convenience methods (`run_in`, `run_once`, `run_every`, `run_daily`, `run_cron`, `run_minutely`, `run_hourly`) accept and forward `where=`
- [ ] FR#3: A sequence of predicates is collapsed into a single zero-arg closure
- [ ] FR#9: Zero-arg predicates set `_predicate_wants_job=False`; one-arg predicates set `True`
- [ ] FR#10: Arity is inspected once at registration time via `inspect.signature()`
- [ ] FR#16: An async predicate raises `TypeError` at registration time
- [ ] AC#5: Tests confirm zero-arg and one-arg dispatch flags are set correctly
- [ ] AC#6: Tests confirm async callable raises `TypeError`
- [ ] AC#10: Tests confirm all seven convenience methods forward `where=` to `schedule()`

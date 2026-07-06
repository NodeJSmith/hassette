---
task_id: "T01"
title: "Add SchedulerPredicate type, ScheduledJob fields, and ExecutionStatus.SKIPPED"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#3", "FR#9", "FR#10", "FR#15", "FR#16", "AC#5", "AC#6", "AC#9"]
---

## Summary
Add the foundational types and dataclass fields that every other task depends on. This includes the `SchedulerPredicate` type alias in `types/types.py`, the `SKIPPED` member on `ExecutionStatus`, the `predicate` and `_predicate_wants_job` fields on `ScheduledJob`, and the `predicate`/`human_description` fields on `ScheduledJobRegistration`. Also extends `ScheduledJob.matches()` and `diff_fields()` to include the predicate in collision detection. Unit tests for all new behavior.

## Target Files
- modify: `src/hassette/types/types.py`
- modify: `src/hassette/scheduler/classes.py`
- modify: `src/hassette/core/registration.py`
- modify: `src/hassette/core/execution_record.py`
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py`
- modify: `tests/unit/scheduler/test_scheduled_job_mark_registered.py`
- modify: `tests/unit/test_model_types.py`
- modify: `src/hassette/test_utils/factories.py`
- read: `src/hassette/bus/listeners.py` (reference for `Listener.predicate` pattern)
- read: `design/specs/003-scheduler-where-predicates/design.md`

## Prompt
Add the foundational types and dataclass fields for scheduler predicate support:

**1. `src/hassette/types/types.py`:**
- Add `SchedulerPredicate` type alias after the existing `Predicate` protocol (around line 145): `SchedulerPredicate = Callable[[], bool] | Callable[["ScheduledJob"], bool]`. Use a forward reference string for `ScheduledJob` to avoid circular imports.
- Add `SKIPPED = "skipped"` to the `ExecutionStatus` StrEnum (line 56-68). Place it after `TIMED_OUT`.

**2. `src/hassette/scheduler/classes.py`:**
- Add a `predicate: "SchedulerPredicate | None" = field(default=None, compare=False)` field to `ScheduledJob`. Place it after the `mode` field (line 227). Add a docstring explaining it stores the normalized predicate callable.
- Add a `_predicate_wants_job: bool = field(default=False, init=False, repr=False, compare=False)` field. This flag is set by `Scheduler.schedule()` after arity inspection — `True` when the predicate accepts a `ScheduledJob` argument.
- Extend `matches()` (line 306-332): add `and self.predicate == other.predicate` to the return expression. Equality comparison — lambdas compare by identity (same as `Listener`).
- Extend `diff_fields()` (line 334-363): add a check for `self.predicate != other.predicate` → `changed.append("predicate")`.

**3. `src/hassette/core/registration.py`:**
- Add `predicate_description: str | None = None` and `human_description: str | None = None` fields to `ScheduledJobRegistration` (after `mode`, around line 120). Follow the same pattern as `ListenerRegistration` (lines 37-41).

**4. `src/hassette/core/execution_record.py`:**
- Update the docstring on `ExecutionRecord.status` (around line 38) to include `'skipped'` in the valid values list.

**5. `src/hassette/test_utils/factories.py`:**
- Extend `make_job_registration()` (around line 57) to accept optional `predicate_description: str | None = None` and `human_description: str | None = None` parameters, mirroring `make_listener_registration()` (lines 27-28, 44-45).

**6. Tests:**
- In `tests/unit/test_model_types.py`, update `TestExecutionStatus` to include `'skipped'` in the expected values.
- In `tests/unit/scheduler/test_scheduled_job_mark_registered.py`, verify that the `predicate` field doesn't interfere with the `mark_registered()` flow — construct a job with a predicate and confirm `mark_registered(db_id)` works normally.
- In `tests/unit/scheduler/test_scheduled_job_lifecycle.py`, add tests for:
  - `ScheduledJob.matches()` with same predicate (matches), different predicate (doesn't match), `None` vs predicate (doesn't match)
  - `ScheduledJob.diff_fields()` includes `"predicate"` when predicates differ
  - Constructing a `ScheduledJob` with `predicate=some_callable` stores it correctly

See `## Architecture > Predicate storage` and `## Architecture > Collision detection` in the design doc for the full specification.

## Focus
- The `predicate` field on `ScheduledJob` uses `compare=False` — it must NOT affect heap ordering (same pattern as `error_handler`, `mode`, and other config fields).
- `_predicate_wants_job` is `init=False` because it's set programmatically by `Scheduler.schedule()`, not passed by callers.
- Lambda equality is identity-based (`is`), not structural. Two `lambda: True` expressions are different objects. This is the same as `Listener`'s behavior — document it in a test.
- `SchedulerPredicate` uses `Callable` from `collections.abc`, not `typing.Callable`. Check the existing imports in `types/types.py`.
- `ScheduledJob` has `__post_init__` (around line 257) — verify the new fields don't interfere with it.
- Gap: `src/hassette/test_utils/factories.py::make_job_registration()` needs the new params to support test creation in later tasks.

## Verify
- [ ] FR#1: `SchedulerPredicate` type alias exists in `types/types.py` with the correct union type
- [ ] FR#3: `ScheduledJob` has a `predicate` field that defaults to `None`
- [ ] FR#9: `ScheduledJob` has a `_predicate_wants_job` field (init=False, compare=False)
- [ ] FR#10: `_predicate_wants_job` is `init=False` — set programmatically, not by callers
- [ ] FR#15: `ScheduledJob.matches()` includes predicate in comparison; `diff_fields()` reports predicate changes
- [ ] FR#16: `ExecutionStatus.SKIPPED` exists with value `"skipped"`
- [ ] AC#5: `_predicate_wants_job` field exists for arity dispatch (actual arity detection is in T02)
- [ ] AC#6: `ExecutionStatus` enum includes `SKIPPED` (async validation is in T02)
- [ ] AC#9: Tests confirm `matches()` includes predicate comparison with identity semantics for lambdas

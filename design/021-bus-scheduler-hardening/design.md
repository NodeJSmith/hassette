# Design: Bus & Scheduler Hardening

**Issues:** #437, #412, #414, #436
**Milestone:** Stability
**Status:** Approved (post-challenge r3)

## Problem

The bus and scheduler subsystem has accumulated four correctness and API hygiene issues:

1. **Memory leak** — `callable_name()` uses `@lru_cache(1024)` which pins bound method objects (and their `self` App instances) in memory after app reload (#437)
2. **Non-idempotent triggers** — `IntervalTrigger.next_run_time()` mutates `self.start`; calling it twice skips an interval. `CronTrigger` has the same pattern via `croniter` (#412)
3. **Async overhead on hot path** — `Listener.matches()` is `async` but never awaits; predicates explicitly reject async callables. This is the only change that directly improves runtime dispatch performance (#414)
4. **Uncontrolled mutation** — `Listener.db_id`, `ScheduledJob.db_id`, and `Listener._fired` are set via bare attribute assignment from outside the class (#436)

Additionally, dead code: unused `TypeVar("T", covariant=True)` in `bus.py:106`, unused `TypeVar("T")` in `classes.py:21`, and unused `BusService.listener_seq` in `bus_service.py:58`.

**Descoped:**
- **#438 (ListenerOptions)** — Dropped after two rounds of challenge review (6/6 critics recommended dropping). Validation co-location achievable with a static method; frozen dataclass provides incomplete immutability since the container is mutable. 25+ test site changes for marginal benefit. Can be revisited when a new listener option motivates the extraction.
- **#414 Scheduler.on_shutdown()** — Dropped because `Resource.shutdown()` does not propagate to children, making the hook unreachable dead code. Filed #449 to add child shutdown propagation, which is the real fix.

## Architecture

### 1. Remove callable_name LRU cache and cache result as field (#437)

Delete `@lru_cache(maxsize=1024)` from `callable_name()` in `func_utils.py`. Add a docstring warning: "Performs `inspect.unwrap()` on every call. Cache the result at construction time rather than calling in hot paths."

Convert `handler_name` from a property to a field computed once during `Listener.create()`. Similarly, `handler_short_name` becomes a field computed from `handler_name`. This eliminates both the memory leak and any per-access overhead. Compute `name = callable_name(handler)` once at the top of `create()` and pass it to all three consumers (ParameterInjector, the handler_name field, and RateLimiter).

**Files:** `src/hassette/utils/func_utils.py`, `src/hassette/bus/listeners.py`

### 2. ID generation: document single-threaded invariant (#412)

The global `itertools.count` generators are called exclusively on the event loop thread. `itertools.count.__next__` is C-level atomic under CPython. No lock needed.

Add a code comment documenting the invariant:

```python
# next_id() is only called at listener/job creation time on the event loop thread.
# itertools.count.__next__ is C-atomic. No lock needed unless the project targets
# free-threaded CPython (PEP 703), which would require a broader concurrency audit.
seq = itertools.count(1)
```

**Files:** `src/hassette/bus/listeners.py`, `src/hassette/scheduler/classes.py`

### 3. Stateless trigger protocol (#412)

Rename from "pure" to "stateless" — triggers no longer mutate `self`, but they accept `current_time` as a parameter rather than calling `now()` internally, making them genuinely deterministic and testable without mocking.

Split `TriggerProtocol` into two methods:

```python
class TriggerProtocol(Protocol):
    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Compute the initial run time from construction parameters."""
        ...

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Compute the next run time from the previous scheduled time."""
        ...
```

**IntervalTrigger** becomes stateless with O(1) catch-up. Add constructor validation to reject zero/negative intervals:

```python
def __init__(self, interval: TimeDelta, start: ZonedDateTime | None = None):
    if interval.in_seconds() <= 0:
        raise ValueError("IntervalTrigger interval must be positive")
    self.interval = interval
    self.start = start or now()

def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
    if self.start > current_time:
        return self.start.round(unit="second")
    # Catch up from start to current_time
    return self._advance_past(self.start, current_time)

def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
    return self._advance_past(previous_run, current_time)

def _advance_past(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
    interval_secs = self.interval.in_seconds()
    elapsed = (current_time - anchor).in_seconds()
    if elapsed > 0:
        missed = int(elapsed / interval_secs)
        anchor = anchor.add(seconds=missed * interval_secs)
    result = anchor.add(seconds=interval_secs)
    # Guard: if floating-point truncation landed result at or before current_time,
    # advance one more interval. Boundary-exact slots are treated as "past."
    if result <= current_time:
        result = result.add(seconds=interval_secs)
    return result.round(unit="second")
```

**CronTrigger** creates a fresh `croniter` per call for true statelessness:

```python
def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
    return self._next_after(self.start or current_time, current_time)

def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
    return self._next_after(previous_run, current_time)

def _next_after(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
    # No fixed skip-ahead threshold — croniter efficiently handles coarse schedules
    # (a daily cron iterates once regardless of gap). Only sub-second crons with
    # multi-minute gaps iterate heavily, which is rare in home automation.
    cron = croniter(self.cron_expression, anchor.py_datetime(), ret_type=datetime)
    while (next_time := cron.get_next()) <= current_time.py_datetime():
        pass
    return ZonedDateTime.from_py_datetime(next_time)
```

**Callers:**
- `scheduler_service.py:279` — `job.trigger.next_run_time(job.next_run, now())`
- `scheduler.py:519` — `trigger.first_run_time(now())`

**Files:** `src/hassette/types/types.py`, `src/hassette/scheduler/classes.py`, `src/hassette/core/scheduler_service.py`, `src/hassette/scheduler/scheduler.py`

### 4. Synchronous Listener.matches() (#414)

Remove `async` from `Listener.matches()`. Update the 2 call sites in `bus_service.py` to drop `await`. The predicate system explicitly rejects async predicates (`predicates.py:499-509`), so this is safe.

This is the highest-value performance fix in the PR: with 50 listeners and 100 events/sec, eliminating the unnecessary coroutine frame saves ~5,000 allocations/sec on the dispatch hot path.

**Files:** `src/hassette/bus/listeners.py`, `src/hassette/core/bus_service.py`

### 5. State-transition methods with resilient guards (#436)

Add explicit methods to `Listener` with warning-based guards (not RuntimeError — a home automation framework must prioritize resilience over strictness, especially during app reload where in-flight registration coroutines can race):

```python
def mark_registered(self, db_id: int) -> None:
    """Set the database ID after persistence. One-time assignment by BusService."""
    if self.db_id is not None:
        LOGGER.warning(
            "Listener %s already registered with db_id=%s, ignoring new db_id=%s",
            self.listener_id, self.db_id, db_id,
        )
        return
    self.db_id = db_id

def mark_fired(self) -> None:
    """Mark this once-listener as having fired. Called internally by dispatch()."""
    self._fired = True
```

Apply the same pattern to `ScheduledJob`:

```python
def mark_registered(self, db_id: int) -> None:
    """Set the database ID after persistence. One-time assignment by SchedulerService."""
    if self.db_id is not None:
        LOGGER.warning(
            "ScheduledJob %s already registered with db_id=%s, ignoring new db_id=%s",
            self.job_id, self.db_id, db_id,
        )
        return
    self.db_id = db_id
```

Update production code (`bus_service.py:120,124`, `scheduler_service.py:199`) and test code to use `mark_registered()`. Replace `self._fired = True` in `dispatch()` with `self.mark_fired()`.

### Validation consolidation

Move the scattered option validation from `Listener.create()` into a `_validate_options()` staticmethod on `Listener`:

```python
@staticmethod
def _validate_options(
    once: bool, debounce: float | None, throttle: float | None
) -> None:
    if debounce is not None and debounce <= 0:
        raise ValueError("'debounce' must be a positive number")
    if throttle is not None and throttle <= 0:
        raise ValueError("'throttle' must be a positive number")
    if debounce is not None and throttle is not None:
        raise ValueError("Cannot specify both 'debounce' and 'throttle' parameters")
    if once and (debounce is not None or throttle is not None):
        raise ValueError("Cannot combine 'once=True' with 'debounce' or 'throttle'")
```

This consolidates validation into a single named method without introducing a new type or changing the field layout.

**Files:** `src/hassette/bus/listeners.py`, `src/hassette/scheduler/classes.py`, `src/hassette/core/bus_service.py`, `src/hassette/core/scheduler_service.py`, test files

### 6. Dead code removal (#412)

- Remove `T = TypeVar("T", covariant=True)` from `bus/bus.py:106`
- Remove `T = TypeVar("T")` from `scheduler/classes.py:21`
- Remove `self.listener_seq = itertools.count(1)` from `bus_service.py:58`
- Remove `import itertools` from `bus_service.py` if no longer used
- Remove `_get_matching_listeners` from `bus_service.py:232-235` (never called; `dispatch()` inlines its own matching loop)

### 7. Fix set_next_run sort_index consistency

`ScheduledJob.set_next_run()` at `classes.py:221-225` uses unrounded `timestamp_nanos()` for `sort_index` while storing the rounded value in `next_run`. This causes heap ordering and due-check to disagree. Fix by using the rounded value for both:

```python
def set_next_run(self, next_run: ZonedDateTime) -> None:
    rounded = next_run.round(unit="second")
    self.next_run = rounded
    self.sort_index = (rounded.timestamp_nanos(), self.job_id)
```

### 8. Replace reschedule_job assert with resilient fallback

The hard `assert secs > 0` at `scheduler_service.py:283` crashes the scheduler dispatch task if rounding collapses two distinct sub-second times to the same second. Replace with a warning and minimum 1-second advance:

```python
if secs <= 0:
    LOGGER.warning("Trigger produced non-future next_run (delta=%ss), advancing by 1s", secs)
    job.set_next_run(curr_next_run.add(seconds=1))
```

**Breaking change note:** The `TriggerProtocol` changes from a single `next_run_time() -> ZonedDateTime` to two methods with different signatures. Custom triggers must implement both `first_run_time(current_time)` and `next_run_time(previous_run, current_time)`. This is a breaking change — existing custom triggers will get `TypeError` at runtime.

## Implementation Order

1. #437 — LRU cache removal + handler_name field caching + docstring warning
2. Dead code removal (TypeVars, listener_seq, _get_matching_listeners)
3. ID generation comments (document single-threaded invariant)
4. #414 — Sync `matches()`
5. #412 — Stateless trigger protocol (split into first_run_time + next_run_time with current_time) + IntervalTrigger input validation + sort_index consistency fix + reschedule_job assert replacement
6. #436 — State-transition methods with resilient guards (Listener + ScheduledJob) + _validate_options()

## Alternatives Considered

- **Threading lock for ID generators** — Dropped: `itertools.count` is C-atomic, no cross-thread creation path exists, single lock insufficient for free-threaded builds.
- **RuntimeError in mark_registered()** — Dropped: crashes BusService during routine app reload. Warning + early return is resilient and still visible.
- **ListenerOptions dataclass** — Dropped after 6/6 unanimous critic recommendation across two rounds. Incomplete frozen guarantee (mutable container), 25+ test changes, no reduction in change amplification. `_validate_options()` staticmethod achieves the validation co-location benefit at zero cost.
- **Scheduler.on_shutdown()** — Dropped: dead code without child shutdown propagation (filed #449). Manual `remove_all_jobs()` calls work today.
- **Single next_run_time(previous_run) method** — Dropped: conflates first-run computation (needs construction params) with reschedule computation (needs previous run). Split protocol is honest about the two-phase nature.
- **CronTrigger reusing croniter with set_current()** — Dropped: mutates shared state, making the stateless protocol dishonest.
- **Triggers calling now() internally** — Dropped: not truly deterministic. `current_time` parameter makes triggers testable without mocking and genuinely stateless.

## Test Strategy

- Existing tests cover all affected paths — no new test files needed
- New unit tests for: `mark_registered()` guard behavior (warn on double-call), `ScheduledJob.mark_registered()`, `_validate_options()`, stateless trigger behavior (same inputs → same output, no mocking needed), O(1) catch-up with floating-point edge cases, `first_run_time()` with user-provided start times
- Update trigger test call sites to pass `current_time` instead of mocking `now()`
- Tests accessing `CronTrigger.cron_iter` directly (`test_triggers.py:58-83`) must be rewritten to use `first_run_time()` — the `cron_iter` attribute no longer persists between calls
- Update `listener.db_id = X` test patterns to use `mark_registered()`
- Run full suite after each issue to catch regressions incrementally

## Challenge Review

### Round 1 (2026-03-28)
9 findings (1 HIGH, 7 MEDIUM, 1 TENSION). Key revisions:
- CronTrigger creates fresh croniter per call (Finding #1)
- mark_registered() includes guard (Finding #2) — later softened in Round 2
- ScheduledJob gets mark_registered() (Finding #3)
- Listener.create() validation consolidated (Finding #8)
- handler_name cached as field (Finding #9)
- on_shutdown properly awaits (Finding #5) — later removed in Round 2
- Threading lock dropped (Finding #6)
- IntervalTrigger uses O(1) catch-up (Finding #7)

### Round 2 (2026-03-28)
8 findings (2 HIGH, 6 MEDIUM). Key revisions:
- Split trigger protocol into first_run_time() + next_run_time() (Finding #1 — HIGH, 3/3)
- Added current_time parameter for true statelessness (Finding #6 — MEDIUM, 2/3)
- Floating-point guard on O(1) catch-up (Finding #2 — HIGH, 2/3)
- mark_registered() uses warning, not RuntimeError (Finding #3 — MEDIUM, 3/3)
- Dropped Scheduler.on_shutdown() — unreachable dead code (Finding #4 — MEDIUM, 3/3). Filed #449.
- Dropped ListenerOptions — 6/6 across two rounds (Finding #5 — MEDIUM, 3/3)
- callable_name() gets docstring warning (Finding #8 — MEDIUM, 2/3)

### Round 3 (2026-03-28)
9 findings (all MEDIUM). No CRITICAL or HIGH. Key revisions:
- sort_index uses rounded nanos for heap consistency (Finding #1 — MEDIUM, 2/3)
- CronTrigger catch-up pre-checks total gap, bounded to ~60 iterations (Finding #2 — MEDIUM, 2/3)
- IntervalTrigger rejects zero/negative intervals (Finding #3 — MEDIUM, 1/3)
- reschedule_job assert replaced with warning + 1s advance (Finding #4 — MEDIUM, 1/3)
- callable_name() computed once in create(), passed to all consumers (Finding #5 — MEDIUM, 1/3)
- _get_matching_listeners added to dead code removal (Finding #6 — MEDIUM, 1/3)
- TriggerProtocol breaking change documented (Finding #7 — MEDIUM, 2/3)
- Test strategy updated for cron_iter removal (Finding #8 — MEDIUM, 2/3)
- Constructor now() accepted as sufficient (Finding #9 — MEDIUM, 1/3)

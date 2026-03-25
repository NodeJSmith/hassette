# Code Audit: Scheduler, Bus, and Event Handling

**Scope:** `src/hassette/scheduler/`, `src/hassette/bus/`, `src/hassette/event_handling/`, and supporting service files (`core/bus_service.py`, `core/scheduler_service.py`)

**Date:** 2026-03-25

---

## CRITICAL

### C1. Global `itertools.count` sequence is not thread-safe

**File:** `src/hassette/scheduler/classes.py:19-25` and `src/hassette/bus/listeners.py:25-29`

**Description:** Both `classes.py` and `listeners.py` use module-level `itertools.count()` objects (`seq`) to generate unique IDs via `next_id()`. While `itertools.count.__next__` is atomic under CPython's GIL, this is an implementation detail, not a language guarantee. More importantly, the codebase has explicit cross-thread spawning in `TaskBucket.spawn()` (line 72-99 of `task_bucket.py`), meaning IDs *could* be generated from different threads. If the project ever runs on a GIL-free build (PEP 703 / free-threaded CPython 3.13+), this becomes a real data race producing duplicate IDs.

**Recommendation:** Replace with `threading.Lock`-protected counters or `atomics`. For immediate safety:

```python
import threading

_seq_lock = threading.Lock()
_seq = itertools.count(1)

def next_id() -> int:
    with _seq_lock:
        return next(_seq)
```

**Severity note:** Marked CRITICAL because duplicate `listener_id` or `job_id` values would cause silent routing/removal bugs that are nearly impossible to diagnose.

---

### C2. `IntervalTrigger.next_run_time()` mutates `self.start` — breaks frozen/shared semantics

**File:** `src/hassette/scheduler/classes.py:53-62`

**Description:** `IntervalTrigger.next_run_time()` mutates `self.start` on every call (lines 57, 60). This has two consequences:

1. **Concurrent calls produce incorrect times.** If two coroutines call `next_run_time()` concurrently (e.g., a job fires while the scheduler is rescheduling), `self.start` gets advanced twice, skipping an interval.
2. **`__eq__` and `__hash__` ignore `start`** (lines 35-41), so two triggers that have diverged in `start` still compare equal. This means `ScheduledJob.matches()` may incorrectly return `True` for jobs with different effective schedules.

The same mutation pattern exists in `CronTrigger.next_run_time()` (line 120-135) via `self.cron_iter.get_next()` which advances internal state.

**Recommendation:** Either:
- Make triggers immutable and return `(next_time, new_trigger)` tuples (functional style), or
- Protect `next_run_time()` with a lock, or
- Document that `next_run_time()` must only be called from the scheduler's single-threaded dispatch path and add an assertion.

The current code only calls `next_run_time()` from `reschedule_job()` which runs inside a single `task_bucket.spawn` task, so this is safe *today*. But the mutable API is a landmine.

---

## HIGH

### H1. Debounced handler silently swallows exceptions

**File:** `src/hassette/bus/rate_limiter.py:81-92`

**Description:** The `delayed_call` closure inside `_debounced_call` catches `asyncio.CancelledError` but does not catch or propagate exceptions from the handler itself. Since the handler runs inside a `task_bucket.spawn`-ed task, any exception is caught by the `TaskBucket._done` callback and logged — but the `Listener.invoke()` call that triggered the debounce has already returned successfully. This means:

- The caller (BusService dispatch) never knows the handler failed.
- The `once` flag removal logic runs before the handler even executes (the debounced task runs later).
- Metrics/telemetry for the handler invocation will not capture the error if the listener has `db_id`.

**Recommendation:** The debounced task should route through the same `CommandExecutor` path that direct invocations use, so telemetry captures the deferred execution. At minimum, the `delayed_call` should log exceptions:

```python
async def delayed_call():
    try:
        await asyncio.sleep(self.debounce)
        await handler(*args, **kwargs)
    except asyncio.CancelledError:
        pass
    except Exception:
        LOGGER.exception("Debounced handler failed")
```

---

### H2. `once=True` listeners with debounce/throttle have race conditions

**File:** `src/hassette/core/bus_service.py:227-248` and `src/hassette/bus/rate_limiter.py:74-92`

**Description:** When a listener has both `once=True` and `debounce`, the `_dispatch` method removes the listener in the `finally` block (line 241/247) immediately after `listener.invoke()` returns. But with debounce, `invoke()` returns instantly (the actual handler is deferred). This means:

1. The listener is removed before the handler ever runs.
2. A second event arriving during the debounce window will not find the listener (already removed), so the debounce reset never happens.
3. The deferred handler runs after the listener is already deregistered — telemetry may reference a non-existent listener.

**Recommendation:** `once=True` should be incompatible with debounce/throttle, or the removal should happen after the deferred handler completes. Add a validation in `HandlerAdapter.__init__` or `Listener.create`:

```python
if once and (debounce or throttle):
    raise ValueError("'once' is incompatible with 'debounce'/'throttle'")
```

---

### H3. `Listener.matches()` is declared `async` but never awaits

**File:** `src/hassette/bus/listeners.py:83-91`

**Description:** `matches()` is an `async` method but contains no `await` expression. The predicate is called synchronously (line 87: `self.predicate(ev)`). Making this `async` forces every caller to `await` it, adding unnecessary coroutine overhead on every event dispatch — which is the hottest path in the system.

**Recommendation:** Make it a plain synchronous method:

```python
def matches(self, ev: "Event[Any]") -> bool:
    if self.predicate is None:
        return True
    matched = self.predicate(ev)
    self.logger.debug(...)
    return matched
```

Update `BusService._get_matching_listeners` and `dispatch` accordingly.

---

### H4. Throttle holds lock during handler execution

**File:** `src/hassette/bus/rate_limiter.py:94-103`

**Description:** `_throttled_call` acquires `self._throttle_lock` and then `await`s the handler *while holding the lock*. If the handler takes a long time (e.g., makes an HTTP call to Home Assistant), all subsequent events for this listener are blocked, not just throttled. Throttling should gate *entry* but not hold a lock during execution.

**Recommendation:**

```python
async def _throttled_call(self, handler, *args, **kwargs):
    async with self._throttle_lock:
        now = time.monotonic()
        if now - self._throttle_last_time < self.throttle:
            return  # drop event
        self._throttle_last_time = now
    # Execute outside the lock
    await handler(*args, **kwargs)
```

---

### H5. Dead code: `ParameterInjector._convert_value` is never called

**File:** `src/hassette/bus/injection.py:144-171`

**Description:** The method `_convert_value` exists on `ParameterInjector` but is never called anywhere in the codebase. The actual conversion is done inline in `_extract_and_convert_parameter` (lines 134-142). The dead method has a stale docstring (references `value` parameter that does not exist in the signature).

**Recommendation:** Remove the dead method to reduce maintenance burden and confusion.

---

### H6. `TypeVar("T", covariant=True)` in bus.py is unused and incorrectly defined

**File:** `src/hassette/bus/bus.py:106`

**Description:** `T = TypeVar("T", covariant=True)` is defined but never used anywhere in the module. Covariant TypeVars are only meaningful in Generic class definitions; a standalone covariant TypeVar used in function signatures would cause Pyright errors. This is dead code that could mislead future developers.

**Recommendation:** Remove the unused TypeVar.

---

## MEDIUM

### M1. `CronTrigger.next_run_time()` has a redundant `pass` and inconsistent catch-up behavior

**File:** `src/hassette/scheduler/classes.py:119-135`

**Description:**
- Line 133 has a bare `pass` that does nothing (the `while` loop body has already run `LOGGER.debug`).
- When the schedule is >1 minute behind, `set_current` resets the iterator (line 130), but then the loop continues calling `get_next()` on the same iterator, potentially yielding a time that is still in the past. The catch-up logic can spin for multiple iterations when the scheduler has been paused.

**Recommendation:** After `set_current`, `break` and re-enter the loop, or restructure as a simpler forward-seek:

```python
def next_run_time(self) -> ZonedDateTime:
    current = now()
    next_time = self.cron_iter.get_next()
    while next_time <= current.py_datetime():
        next_time = self.cron_iter.get_next()
    return ZonedDateTime.from_py_datetime(next_time)
```

---

### M2. `ScheduledJob` uses `assert` for runtime validation

**File:** `src/hassette/core/scheduler_service.py:287`

**Description:** `assert secs > 0` is used to validate that the next run time is in the future. Assertions are stripped when Python runs with `-O`. This is a runtime invariant that should use a proper exception.

**Recommendation:**

```python
if secs <= 0:
    raise ValueError(f"Next run time must be in the future, got delta={secs}s for job {job}")
```

Similarly, the `assert` statements in `Scheduler.__init__` (scheduler.py:137) and `Bus.__init__` (bus.py:133) should be replaced with explicit checks.

---

### M3. `get_start_dtme` calls `now()` multiple times — time skew between calls

**File:** `src/hassette/scheduler/scheduler.py:566-568`

**Description:** The `ZonedDateTime.from_system_tz()` call uses `now().year`, `now().month`, `now().day` as separate calls. If this runs at midnight boundary, year/month/day could be inconsistent (e.g., `now()` returns Dec 31 for year, then Jan 1 for month/day).

**Recommendation:** Capture `now()` once:

```python
current = now()
start_dtme = ZonedDateTime.from_system_tz(
    year=current.year, month=current.month, day=current.day,
    hour=start_time.hour, minute=start_time.minute
)
```

---

### M4. `OP_LIST = list(OPS.__args__)` accesses a private typing attribute

**File:** `src/hassette/event_handling/conditions.py:62`

**Description:** `OPS.__args__` is an implementation detail of `typing.Literal`. While it works in CPython 3.11+, it is not part of the public API and could change. `OP_LIST` is only used for the error message in `Comparison.__init__`.

**Recommendation:** Use `typing.get_args(OPS)` which is the public API:

```python
from typing import get_args
OP_LIST = list(get_args(OPS))
```

---

### M5. `Bus.on()` calls `add_listener` then returns `Subscription` — but add is async

**File:** `src/hassette/bus/bus.py:206-210`

**Description:** `self.add_listener(listener)` returns an `asyncio.Task[None]` that is not awaited. The listener may not be fully registered when `Subscription` is returned to the caller. If the caller immediately uses the subscription to check listener state or if an event fires before the task runs, the listener won't be found.

This is by design (fire-and-forget registration), but the `Subscription` object's `unsubscribe()` method (line 206-207) also fires and forgets. This means a rapid `subscribe -> unsubscribe` sequence could result in the unsubscribe running before the add completes, leaving the listener registered permanently.

**Recommendation:** Document this behavior explicitly, or make `on()` an async method that awaits registration before returning the subscription.

---

### M6. Duplicate `TYPE_CHECKING` import blocks in `predicates.py`

**File:** `src/hassette/event_handling/predicates.py:72-74` and `77-80`

**Description:** There are two separate `if typing.TYPE_CHECKING:` blocks. The first imports `Event` and `Predicate`; the second imports `RawStateChangeEvent`, `CallServiceEvent`, `Event`, `HassEvent`, and `Predicate`. `Event` and `Predicate` are imported in both blocks.

**Recommendation:** Merge into a single block:

```python
if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent
    from hassette.events import CallServiceEvent, Event, HassEvent
    from hassette.types import ChangeType, Predicate
```

---

### M7. `ListenerMetrics.avg_duration_ms` divides by `total_invocations` which includes failures

**File:** `src/hassette/bus/metrics.py:48-51`

**Description:** The `avg_duration_ms` property divides `total_duration_ms` by `total_invocations`, which includes successful, failed, DI-failure, and cancelled invocations. Failed invocations (which may abort early) will skew the average downward, potentially masking slow successful invocations. This is a design choice but worth documenting.

**Recommendation:** Add a docstring clarifying this includes all invocation types, or add a separate `avg_successful_duration_ms` property.

---

### M8. `Router.get_listeners_by_owner` returns the internal list — caller can mutate it

**File:** `src/hassette/core/bus_service.py:478-479`

**Description:** `get_listeners_by_owner` returns `self.owners.get(owner, [])` which returns the actual internal list. Any mutation by the caller (append, remove) would corrupt the router's state. The `Bus.get_listeners()` method exposes this to app code.

**Recommendation:** Return a copy:

```python
async def get_listeners_by_owner(self, owner: str) -> list["Listener"]:
    async with self.lock:
        return list(self.owners.get(owner, ()))
```

---

## LOW

### L1. `DomainMatches`, `EntityMatches`, `ServiceMatches` recreate condition objects on every call

**File:** `src/hassette/event_handling/predicates.py:360-362, 377-379, 394-396`

**Description:** Each `__call__` invocation creates a new `Glob()` condition and `ValueIs()` predicate. For high-frequency events (state_changed fires many times per second), this creates unnecessary GC pressure. The glob check result is deterministic for the same `self.domain`/`self.entity_id`/`self.service` value.

**Recommendation:** Pre-compute the condition in `__post_init__`:

```python
@dataclass(frozen=True)
class EntityMatches:
    entity_id: str
    _condition: "ChangeType" = field(init=False, repr=False)

    def __post_init__(self):
        cond = Glob(self.entity_id) if is_glob(self.entity_id) else self.entity_id
        object.__setattr__(self, "_condition", cond)

    def __call__(self, value, /):
        return ValueIs(source=get_entity_id, condition=self._condition)(value)
```

Or go further and pre-build the `ValueIs` instance too.

---

### L2. `StateFrom.__call__` and `StateTo.__call__` create a new `ValueIs` on every invocation

**File:** `src/hassette/event_handling/predicates.py:243-244, 256-257`

**Description:** Same pattern as L1 — `ValueIs(source=..., condition=...)` is constructed on every event. These predicates are on the critical path for every state change event with `changed_from`/`changed_to` filters.

**Recommendation:** Pre-build the `ValueIs` in `__post_init__`.

---

### L3. `_recursive_get_differences` logs at DEBUG level for every key — extremely verbose

**File:** `src/hassette/event_handling/accessors.py:297-313`

**Description:** The function logs at DEBUG for every excluded key, every nested recursion, every detected change, and the final result dict. For entities with many attributes (e.g., media players with 20+ attributes), this produces 30+ log lines per state change event.

**Recommendation:** Reduce to a single summary log at the function's top-level call, or gate behind a `TRACE` level.

---

### L4. `Scheduler` has no `on_shutdown` to clean up its jobs

**File:** `src/hassette/scheduler/scheduler.py:125`

**Description:** The `Bus` resource has an `on_shutdown` that calls `remove_all_listeners()` (bus.py:136-138). The `Scheduler` resource has no equivalent. While the `SchedulerService` handles shutdown via its `serve()` loop exit, individual `Scheduler` instances (one per app) do not proactively cancel their jobs. If an app is reloaded without full shutdown, its jobs may linger.

**Recommendation:** Add:

```python
async def on_shutdown(self) -> None:
    self.remove_all_jobs()
```

---

### L5. `Subscription.manage()` context manager is synchronous but `unsubscribe()` is fire-and-forget async

**File:** `src/hassette/bus/listeners.py:223-228`

**Description:** `manage()` is a `@contextlib.contextmanager` that calls `self.unsubscribe()` in its `finally` block. Since `unsubscribe()` spawns an async task via `remove_listener()`, the listener is not guaranteed to be removed when the `with` block exits. An async context manager would be more appropriate if guaranteed cleanup is needed.

**Recommendation:** Document that cleanup is best-effort, or provide an `async_manage()` alternative using `contextlib.asynccontextmanager`.

---

### L6. `make_async_handler` docstring is missing the `task_bucket` parameter

**File:** `src/hassette/bus/listeners.py:235-248`

**Description:** The docstring for `make_async_handler` lists only `fn` in Args, but the function also takes `task_bucket`.

**Recommendation:** Update the docstring.

---

## Summary

| Severity | Count | Verdict |
|----------|-------|---------|
| CRITICAL | 2     | **Block** — C1 (thread-safety of ID generation) and C2 (trigger mutation) should be addressed |
| HIGH     | 6     | Fix before next release |
| MEDIUM   | 8     | Address when convenient |
| LOW      | 6     | Nice to have |

### Overall Assessment

The architecture is well-structured with clear separation between the user-facing `Bus`/`Scheduler` resources and the underlying `BusService`/`SchedulerService` workers. Error isolation is solid — exceptions in handlers are caught and logged in both `_dispatch` (bus_service.py:236-238) and `run_job` (scheduler_service.py:257-260), with the `TaskBucket` providing a backstop via its `_done` callback. The predicate/condition/accessor layering is clean and composable.

The primary concerns are:
1. **Mutable trigger state** (C2) which is safe today but fragile.
2. **Debounce/throttle interactions with `once` and telemetry** (H1, H2, H4) — the rate limiter needs a design pass.
3. **Minor performance overhead** on the hot dispatch path from unnecessary `async` on `matches()` and per-call object creation in predicates (H3, L1, L2).

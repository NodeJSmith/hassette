# Scheduler, Bus, and Event Handling Audit

## Summary

The scheduler, bus, and event handling subsystems are well-architected overall. The separation between per-owner `Scheduler`/`Bus` resources and centralized `SchedulerService`/`BusService` services is clean and supports proper lifecycle management. The predicate/condition/accessor composition pattern in `event_handling` is well-designed and composable. Error isolation is solid thanks to `CommandExecutor` wrapping all app-owned handler and job executions with full telemetry.

The most significant issues are: mutable trigger state creating implicit coupling between trigger objects and the scheduler loop, a potential race between concurrent dispatches of scheduled jobs, and the lack of a backpressure mechanism on the bus dispatch fanout. There are no critical issues.

---

## HIGH

### H1. IntervalTrigger mutates `self.start` on every `next_run_time()` call

**Location:** `src/hassette/scheduler/classes.py:53-62`

**Description:** `IntervalTrigger.next_run_time()` advances `self.start` as a side effect. This means the trigger object carries mutable state that is modified by the scheduler service during rescheduling (`scheduler_service.py:283`). If `next_run_time()` were ever called twice without an intervening execution (e.g., during a retry or diagnostic introspection), the schedule would silently skip an interval. The `CronTrigger` has the same pattern via its `croniter` internal iterator state.

The `while` loop in `IntervalTrigger.next_run_time()` also advances `self.start` one extra time beyond the catch-up loop (line 60), then returns a rounded version of the already-advanced start. This means the trigger's internal `start` and the returned `next_run` can drift apart by rounding differences.

**Recommendation:** Make `next_run_time()` a pure computation that takes the previous run time as input and returns the next one, rather than mutating internal state. The scheduler service already has the `job.next_run` it can pass in. This also makes triggers safe for concurrent or diagnostic use.

---

### H2. Scheduler resource has no `on_shutdown` hook for owned job cleanup

**Location:** `src/hassette/scheduler/scheduler.py` (entire class)

**Description:** The `Bus` resource implements `on_shutdown` to call `remove_all_listeners()`, but `Scheduler` has no corresponding `on_shutdown`. Job cleanup only happens via `App.cleanup()` (in `app.py:144`), which explicitly calls `self.scheduler.remove_all_jobs()`. If a non-App owner creates a `Scheduler` resource directly (the constructor allows this), its jobs will never be cleaned up on shutdown.

The asymmetry between Bus (self-cleaning) and Scheduler (relies on parent cleanup) is a design smell even if the current app lifecycle happens to handle it.

**Recommendation:** Add `on_shutdown` to `Scheduler` that calls `self.remove_all_jobs()`, mirroring the Bus pattern. This makes the Scheduler self-contained and safe for any owner type.

---

### H3. Global `itertools.count` ID generators are module-level singletons

**Location:** `src/hassette/scheduler/classes.py:19`, `src/hassette/bus/listeners.py:25`

**Description:** Both `ScheduledJob.job_id` and `Listener.listener_id` use module-level `itertools.count(1)` singletons (`seq`). These counters:

1. Never reset between test runs in the same process, so test assertions on specific IDs are fragile.
2. Are not thread-safe for the `next()` call on CPython (safe under GIL, but not guaranteed by the language spec).
3. Cannot be introspected or reset, making debugging harder.

The IDs are used as heap ordering tiebreakers (scheduler) and for listener deduplication (bus router), so uniqueness matters.

**Recommendation:** Move the counter into the owning service (`SchedulerService` and `BusService`) as instance attributes. This scopes IDs to a single framework instance and makes tests deterministic. If cross-thread safety is needed, use `threading.Lock` or `atomicint`.

---

### H4. Throttled handler holds the lock during the entire handler execution

**Location:** `src/hassette/bus/rate_limiter.py:94-103`

**Description:** `_throttled_call` acquires `self._throttle_lock` and then awaits the handler while holding it:

```python
async with self._throttle_lock:
    now = time.monotonic()
    if now - self._throttle_last_time >= self.throttle:
        self._throttle_last_time = now
        await handler(*args, **kwargs)
```

If the handler is slow (e.g., calls an HA service), all subsequent events for this listener are queued behind the lock. The throttle interval effectively becomes `max(throttle_interval, handler_duration)`. This also means events arriving during handler execution are silently dropped (the timestamp check will pass, but the lock blocks them until after completion, at which point the time check fails).

**Recommendation:** Release the lock before calling the handler. Record `_throttle_last_time` inside the lock, release it, then call the handler. This ensures the throttle window is based on when the handler *starts*, not when it *finishes*.

---

## MEDIUM

### M1. Debounce spawns a fire-and-forget task with no error propagation

**Location:** `src/hassette/bus/rate_limiter.py:74-92`

**Description:** `_debounced_call` spawns a background task via `task_bucket.spawn()` and returns immediately. The caller (`HandlerAdapter.call`) returns to the bus dispatch without awaiting the debounced execution. This means:

1. The caller never sees exceptions from the debounced handler (they surface only in `TaskBucket._done` callback logging).
2. The `CommandExecutor`'s `_execute_handler` timing and error recording wraps the `listener.invoke()` call, but for debounced handlers, `invoke()` returns instantly and the actual execution happens later in a separate task -- outside the executor's telemetry window.

**Recommendation:** Either (a) have the debounce task go through `CommandExecutor.execute` for proper telemetry, or (b) document that debounced handlers bypass execution metrics. The current behavior silently produces misleading telemetry (near-zero duration, always "success").

---

### M2. Bus `dispatch` creates unbounded concurrent handler tasks

**Location:** `src/hassette/core/bus_service.py:199`

**Description:** For each matching listener, `dispatch` calls `task_bucket.spawn(self._dispatch(...))`. There is no concurrency limit. A single event that matches many listeners (e.g., a glob `*` subscription) will spawn one task per listener simultaneously. A burst of state_changed events (common on HA restart) could create hundreds of concurrent tasks.

The `TaskBucket` uses a `WeakSet`, so completed tasks are GC'd, but there's no admission control or semaphore to limit how many run at once.

**Recommendation:** Consider adding a configurable concurrency limit (e.g., `asyncio.Semaphore`) to `BusService.dispatch` or per-listener. This prevents resource exhaustion during event storms. The scheduler already has implicit backpressure via its sleep/wakeup cycle.

---

### M3. Scheduler `_dispatch_and_log` spawns jobs concurrently with no concurrency limit

**Location:** `src/hassette/core/scheduler_service.py:87`

**Description:** When multiple jobs are due simultaneously (e.g., after a long sleep or on startup), all are dispatched concurrently via `task_bucket.spawn`. The `pop_due_and_peek_next` can return an unbounded number of due jobs. If many cron jobs share the same schedule (e.g., every minute at :00), they all fire at once with no ordering guarantees or concurrency cap.

**Recommendation:** Consider dispatching due jobs sequentially or with a bounded semaphore, especially for jobs owned by the same app. This prevents resource contention and makes execution order deterministic.

---

### M4. `ScheduledJob` is a mutable dataclass used as a heap element

**Location:** `src/hassette/scheduler/classes.py:138-219`

**Description:** `ScheduledJob` is `@dataclass(order=True)` and placed in a `heapq`. However, `set_next_run()` mutates `sort_index` after the job may have been added to the heap (during rescheduling in `reschedule_job`). The reschedule path calls `set_next_run` then re-enqueues, which is correct, but if any code path mutates a job's `sort_index` while it's in the heap, the heap invariant breaks silently.

The `cancelled` flag is also mutated in-place (`job.cancel()`), and the scheduler checks it at dispatch time. This mutation pattern works but creates a class of bugs where stale heap entries aren't properly handled.

**Recommendation:** Consider making `ScheduledJob` frozen and creating a new instance for rescheduling, or at minimum add a comment/assertion that `set_next_run` must only be called on jobs that have been popped from the heap.

---

### M5. `Listener.matches()` is async but predicates are synchronous

**Location:** `src/hassette/bus/listeners.py:83-91`

**Description:** `Listener.matches()` is declared `async` but only calls `self.predicate(ev)` synchronously (predicates explicitly reject async callables via `compare_value`). The `async` keyword adds coroutine overhead on every event-listener match check for no benefit.

**Recommendation:** Make `matches()` a regular synchronous method. The `BusService.dispatch` method would need to adjust its call sites accordingly (remove `await`).

---

### M6. No test coverage for rate limiter (`RateLimiter`) behavior

**Location:** `src/hassette/bus/rate_limiter.py`

**Description:** There are no dedicated tests for the `RateLimiter` class (no `test_rate_limiter*.py` found). The debounce and throttle behaviors are fundamental to correct bus operation and have subtle timing-dependent edge cases (debounce cancellation, throttle lock contention, interaction with shutdown). The integration bus tests may exercise these indirectly, but dedicated unit tests would catch regressions.

**Recommendation:** Add unit tests covering: debounce cancellation on rapid events, throttle dropping events within the window, interaction between rate limiting and shutdown/cancellation, and the lock-during-execution behavior noted in H4.

---

### M7. Event stream has a fixed buffer but `send_event` blocks the producer on full buffer

**Location:** `src/hassette/core/event_stream_service.py:30-31, 42-44`

**Description:** The event stream uses `create_memory_object_stream` with a configurable `buffer_size`. When the buffer is full, `send_event` (which calls `_send_stream.send()`) will block the caller (typically the WebSocket service or file watcher). This provides backpressure but means a slow `BusService.dispatch` can stall the WebSocket event reader, causing the HA WebSocket connection to back up.

**Recommendation:** Consider using `send_nowait` with overflow logging or a dropping strategy for non-critical events, while keeping blocking behavior for critical hassette events. Alternatively, document the backpressure behavior so operators can tune `hassette_event_buffer_size`.

---

## LOW

### L1. `_convert_value` in `ParameterInjector` is dead code

**Location:** `src/hassette/bus/injection.py:144-171`

**Description:** The `_convert_value` method on `ParameterInjector` is never called. The actual conversion logic lives in `_extract_and_convert_parameter` which uses the `conv` variable directly. The dead method has a stale docstring referencing a different parameter name (`value` vs `extracted_value`).

**Recommendation:** Remove the dead method.

---

### L2. `StateComparison` and `AttrComparison` auto-instantiate classes passed as conditions

**Location:** `src/hassette/event_handling/predicates.py:269-273, 316-319`

**Description:** Both predicates check `inspect.isclass(self.condition)` in `__post_init__` and auto-instantiate it with `self.condition()`. This is a defensive measure against users passing `C.Increased` instead of `C.Increased()`. While helpful, the `LOGGER.warning` message includes `stacklevel=2` which won't point to the user's code (it points to the dataclass machinery). The `object.__setattr__` on a frozen dataclass is also an unusual pattern.

**Recommendation:** Consider raising a `TypeError` instead of silently fixing the mistake, or fix the `stacklevel` to point to the caller.

---

### L3. `HeapQueue` uses linear scan for `remove_item` and `remove_where`

**Location:** `src/hassette/core/scheduler_service.py:504-527`

**Description:** `remove_item` uses `list.__contains__` (O(n)) followed by `list.remove` (O(n)) and `heapify` (O(n)). `remove_where` does a list comprehension filter (O(n)) plus `heapify` (O(n)). For typical automation workloads (tens to low hundreds of jobs), this is fine. Would only matter if thousands of jobs were scheduled.

**Recommendation:** No action needed for current scale. If job counts grow, consider a dict-based lookup index.

---

### L4. `App.cleanup()` calls `task_bucket.cancel_all()` twice

**Location:** `src/hassette/app/app.py:140-153` and `src/hassette/resources/base.py:323-336`

**Description:** `App.cleanup()` calls `super().cleanup()` (which calls `self.task_bucket.cancel_all()` at line 335), then immediately calls `self.task_bucket.cancel_all()` again in the gathered tasks at line 146. The second call is a no-op since all tasks were already cancelled, but it's wasted work and confusing.

**Recommendation:** Remove the redundant `cancel_all()` call in `App.cleanup()`.

---

### L5. `Router.get_topic_listeners` deduplicates by `id(listener)` instead of `listener_id`

**Location:** `src/hassette/core/bus_service.py:458-462`

**Description:** The dedup set uses `id(listener)` (Python object identity) rather than `listener.listener_id`. Since listeners are stored by reference in the router's lists, `id()` works correctly in practice. But if a listener were ever copied or reconstructed (e.g., during serialization for diagnostics), `id()`-based dedup would fail.

**Recommendation:** Use `listener.listener_id` for deduplication to be robust against any future code that creates listener copies.

---

### L6. Predicate `summarize()` methods return generic strings

**Location:** `src/hassette/event_handling/predicates.py` (various classes)

**Description:** Several predicates return unhelpful summaries: `ValueIs.summarize()` returns `"custom condition"` regardless of its actual `source` and `condition`. `Guard.summarize()` always returns `"custom condition"`. The `human_description` stored in the DB listener registration depends on these summaries.

**Recommendation:** Improve `ValueIs.summarize()` to include the condition repr, and have `Guard.summarize()` attempt to use the wrapped function's name.

---

## Positive Observations

- **Error isolation is thorough.** The `CommandExecutor` catches all exception types for both handler invocations and job executions, producing telemetry records regardless of outcome. The `TaskBucket._done` callback provides a safety net for unhandled exceptions in spawned tasks.
- **Lifecycle management is well-structured.** The `Resource`/`Service` base classes with `@final` enforcement prevent accidental override of critical lifecycle methods.
- **The predicate/condition/accessor composition** is clean and extensible. The separation of concerns (accessors extract, conditions test, predicates combine) enables powerful filtering without complex inheritance.
- **The `FairAsyncRLock`** for both the scheduler queue and bus router prevents starvation under contention.
- **Bus topic expansion** (entity-specific -> domain-wildcard -> base topic) with first-match-wins deduplication is a well-designed pattern that balances specificity with flexibility.
- **Dependency injection in handlers** via `Annotated` types is elegant and avoids the boilerplate of manual event field extraction.

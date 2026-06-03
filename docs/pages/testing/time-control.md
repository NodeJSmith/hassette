# Time Control

The time control API freezes the harness clock and advances it manually. This makes scheduler-driven behavior deterministic in tests.

!!! note "`whenever` is installed automatically"
    Code examples on this page import from [`whenever`](https://whenever.readthedocs.io/en/latest/), Hassette's date/time library. It ships as a direct dependency of `hassette`, so no separate install is needed.

The canonical sequence is: freeze, advance, trigger.

```python
--8<-- "pages/testing/snippets/testing_time_control_sequence.py"
```

`freeze_time` pins the clock at a known point. `advance_time` moves it forward. `trigger_due_jobs` fires every job whose scheduled time is at or before the frozen clock.

## `freeze_time(instant)`

`freeze_time` patches `hassette.utils.date_utils.now` to return a fixed time. The `instant` parameter accepts an `Instant` or `ZonedDateTime` from [`whenever`](https://whenever.readthedocs.io/en/latest/).

```python
--8<-- "pages/testing/snippets/testing_freeze_time.py"
```

Calling `freeze_time` again replaces the frozen time. The old patchers stop and new ones start. The clock unfreezes automatically when the harness `async with` block exits.

## `advance_time(*, seconds, minutes, hours)`

`advance_time` moves the frozen clock forward by the given delta. The `seconds`, `minutes`, and `hours` keywords combine in a single call.

```python
--8<-- "pages/testing/snippets/testing_advance_time.py"
```

!!! warning "`advance_time` does not trigger jobs"
    Advancing the clock does not dispatch any scheduled jobs. Call `trigger_due_jobs()` explicitly afterward. Without it, jobs accumulate silently and assertions on side effects fail.

## `trigger_due_jobs()`

`trigger_due_jobs` fires all jobs whose scheduled time is at or before the current frozen clock. It returns the number of jobs dispatched and completed.

```python
--8<-- "pages/testing/snippets/testing_trigger_due_jobs.py"
```

`trigger_due_jobs` operates on a snapshot of due jobs taken at the moment of the call. Jobs re-enqueued during dispatch (repeating jobs) are not included in that snapshot and are not re-triggered in the same call. This prevents infinite loops when the clock is frozen.

If dispatched jobs send events through the bus, downstream handler tasks are spawned but not drained by `trigger_due_jobs`. A `simulate_*` call or `_drain_task_bucket` call afterward drains those handler tasks before assertions run.

## Next Steps

- **[Concurrency & pytest-xdist](concurrency.md)**: time-control lock interaction with parallel test workers
- **[Testing index](index.md)**: harness overview and setup

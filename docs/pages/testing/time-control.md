# Time Control

Test scheduler-driven behavior by freezing time and advancing it manually.

The canonical sequence for any time-control test is:

```python
--8<-- "pages/testing/snippets/testing_time_control_sequence.py"
```

!!! note "`whenever` is installed automatically"
    Time control examples on this page import from [`whenever`](https://whenever.readthedocs.io/) — Hassette's date/time library. It's a direct dependency of `hassette`, so it's installed automatically. No separate install needed.

## `freeze_time(instant)`

Freezes `hassette.utils.date_utils.now` at the given time. Accepts an `Instant` or `ZonedDateTime` from the [`whenever`](https://whenever.readthedocs.io/) library. No stdlib `datetime` — the scheduler uses `whenever` types throughout.

```python
--8<-- "pages/testing/snippets/testing_freeze_time.py"
```

`freeze_time` is idempotent — calling it again replaces the frozen time. The clock is automatically unfrozen when the `async with` block exits.

## `advance_time`

Advances the frozen clock by the given delta.

```python
--8<-- "pages/testing/snippets/testing_advance_time.py"
```

!!! warning "`advance_time` alone has no effect on scheduled jobs"
    Moving the clock forward does not trigger any jobs. You must call `trigger_due_jobs()` explicitly after advancing time — otherwise jobs accumulate silently and your assertions will fail.

## `trigger_due_jobs`

Fires all jobs whose scheduled time is at or before the current frozen time. Returns the number of jobs dispatched.

```python
--8<-- "pages/testing/snippets/testing_trigger_due_jobs.py"
```

Jobs re-enqueued during dispatch (repeating jobs) are not re-triggered in the same call — only the snapshot of due jobs at the moment of the call is processed. This prevents infinite loops when the clock is frozen.

## What's Next

- [Concurrency & pytest-xdist](concurrency.md) — Understand how the time-control lock interacts with parallel test runners
- [Quick Start](index.md) — Back to the harness basics

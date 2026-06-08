# Concurrency & pytest-xdist

Two isolation mechanisms protect test state. Each targets a different scope.

## DrainFailure Exception Hierarchy

`DrainFailure` catches any drain-related failure from a `simulate_*` call that does not settle cleanly. Two concrete subclasses distinguish the failure mode.

`DrainError` fires when handler tasks raise non-cancellation exceptions during drain. Its `task_exceptions` attribute is a `list[tuple[str, BaseException]]`, one entry per failed task.

`DrainTimeout` fires when the drain does not reach quiescence within the deadline. The exception message includes pending task names and a debounce hint when applicable.

`DrainTimeout` does not inherit from `TimeoutError`. Test code catches `DrainTimeout` or `DrainFailure` around `simulate_*` calls, not `TimeoutError`.

```python
--8<-- "pages/testing/snippets/testing_drain_exceptions.py"
```

Harness startup timeouts raise `TimeoutError`, not a `DrainFailure` subclass. A startup timeout fires when `on_initialize()` exceeds its deadline. [Test Harness Reference](harness.md) covers startup lifecycle.

## Same-Class Concurrency (Always Applies)

`AppTestHarness` acquires a per-App-class `asyncio.Lock` around the `app_manifest` read-modify-write. A reference counter sets `app_manifest` on the first entry and restores it only when the last harness exits. Multiple harnesses for the same [App][hassette.app.app.App] class can run concurrently via `asyncio.gather()`. Harnesses for different `App` classes never share a lock.

## Time-Control Concurrency (freeze_time Only)

`freeze_time` acquires a process-global `threading.Lock` (non-reentrant). Only one harness may hold the time lock at a time, regardless of `App` class. The lock releases when the `AppTestHarness` context manager exits.

A second harness that attempts to acquire the time lock raises `RuntimeError: freeze_time is already held by another harness`. Running `freeze_time` tests serially avoids this, either by avoiding concurrency or by grouping them with `xdist_group` (see below).

## Parallel Test Suites (pytest-xdist)

Each xdist worker runs in its own process with its own `threading.Lock`. Workers cannot interfere with each other's frozen clock. The risk is within a single worker. `freeze_time` tests assigned to the same worker may interleave during concurrent async execution.

`@pytest.mark.xdist_group("time_control")` routes all marked tests to the same worker and serializes them. Tests that do not call `freeze_time` do not need this marker.

```python
--8<-- "pages/testing/snippets/testing_xdist_group.py"
```

Without `-n`, pytest runs sequentially in a single process. The marker has no effect there.

## pytest-asyncio Mode

`asyncio_mode = "auto"` is required. Without it, async tests silently pass without executing. The [Testing index](index.md#install) covers setup and the false-green warning.

## Next Steps

- **[Time Control](time-control.md)**: Freezing and advancing time in tests
- **[Factories](factories.md)**: Event factories and `RecordingApi` coverage boundary
- **[Testing index](index.md)**: Harness setup and quick start

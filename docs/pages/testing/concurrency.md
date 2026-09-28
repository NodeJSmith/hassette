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

`AppTestHarness` synthesizes a fresh manifest for each app instance and passes it to the constructor. Nothing is written to the shared [App][hassette.app.app.App] class, so multiple harnesses for the same class run concurrently via `asyncio.gather()` without interfering. No lock guards this path — there is no shared mutable state to protect.

## Time-Control Concurrency (freeze_time Only)

`freeze_time` acquires a process-global `threading.Lock` (non-reentrant). Only one harness may hold the time lock at a time, regardless of `App` class. The lock releases when the `AppTestHarness` context manager exits.

A second harness that attempts to acquire the time lock raises `RuntimeError: freeze_time is already held by another harness`. This happens only when two harnesses that call `freeze_time` are alive at the same time in one process, for example two harnesses run concurrently inside a single test. Separate test functions run one after another, so each releases the lock before the next acquires it. Within a single test, call `freeze_time` on only one harness at a time.

## Parallel Test Suites (pytest-xdist)

Install `pytest-xdist` to enable parallel test execution:

```bash
pip install pytest-xdist   # or: uv add --dev pytest-xdist
```

Each xdist worker runs in its own process with its own `threading.Lock`. Workers cannot interfere with each other's frozen clock, and a single worker runs its assigned tests one at a time. `freeze_time` tests need no special marker or distribution mode under xdist.

## pytest-asyncio Mode

`asyncio_mode = "auto"` is required. Without it, async tests silently pass without executing. The [Testing index](index.md#install) covers setup and the false-green warning.

## Next Steps

- **[Time Control](time-control.md)**: Freezing and advancing time in tests
- **[Factories](factories.md)**: Event factories and `RecordingApi` coverage boundary
- **[Testing index](index.md)**: Harness setup and quick start

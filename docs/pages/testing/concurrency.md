# Concurrency & pytest-xdist

The harness has two independent isolation mechanisms. Understanding which applies when prevents confusing deadlocks.

## Same-Class Concurrency (always applies)

`AppTestHarness` uses a **per-App-class `asyncio.Lock`** as a narrow critical section around the `app_manifest` read-modify-write and hermetic config validation. The lock is held only during synchronous attribute operations — not during app startup or teardown.

- Two harnesses for the **same App class** can run concurrently in the same event loop. Using `asyncio.gather()` with multiple harnesses that share a class is safe — a reference counter ensures `app_manifest` is set on the first entry and restored only when the last harness exits.
- Two harnesses for **different App classes** can also run concurrently without conflict.

## Time-Control Concurrency (`freeze_time` only)

`freeze_time` additionally uses a **process-global non-reentrant lock**. Only one harness at a time may hold the time lock in a process, regardless of which App class it tests.

- Sequential tests in the same worker are safe — the lock is released when the `async with` block exits cleanly.
- If two harnesses compete for the time lock, the second one raises `RuntimeError: freeze_time is already held by another harness`.

## Parallel Test Suites (pytest-xdist)

Each xdist worker runs in its own process with its own time lock — workers cannot interfere with each other's frozen clock. The actual concern is within a single worker: `freeze_time` tests that are not grouped may interleave if the worker runs multiple async tests concurrently. Mark all `freeze_time` tests with the same `xdist_group` to serialize them within one worker:



```python
--8<-- "pages/testing/snippets/testing_xdist_group.py"
```

If you run pytest sequentially (no `-n` flag), you do not need this marker.

## pytest-asyncio Mode

See [Installation](index.md#installation) on the Quick Start page for the required `asyncio_mode = "auto"` configuration and the false-green warning.

## `DrainFailure` Exception Hierarchy

The drain exception hierarchy is rooted at `DrainFailure` so callers can catch any drain-related failure uniformly.

`DrainFailure` has two concrete subclasses:

- **`DrainError`** — one or more spawned handler tasks raised a non-cancellation exception. `e.task_exceptions` is a list of `(task_name, exception)` pairs.
- **`DrainTimeout`** — the drain did not reach quiescence within the configured timeout. The diagnostic message includes pending task names and a hint to check for debounced handlers.

`DrainTimeout` deliberately does **not** inherit from `TimeoutError`. Callers should catch `DrainTimeout` or `DrainFailure` — not `TimeoutError` — around `simulate_*` calls.

Harness startup timeouts (raised if `on_initialize()` takes more than 5 seconds) are a separate `TimeoutError` and are not `DrainFailure` subclasses. See [Harness Startup Failures](index.md#harness-startup-failures) on the Quick Start page.

## Next Steps

- **[Factories & Internals](factories.md)**: Event factories and `RecordingApi` coverage boundary
- **[Time Control](time-control.md)**: How to freeze and advance time
- **[Quick Start](index.md)**: Back to the harness basics

# Concurrency & pytest-xdist

The harness has two independent isolation mechanisms. Understanding which applies when prevents confusing deadlocks.

## Same-Class Concurrency (always applies)

`AppTestHarness` holds a **per-App-class `asyncio.Lock`** for the entire `async with` block. This applies to every harness, whether or not you call `freeze_time`.

- Two harnesses for the **same App class** cannot run concurrently in the same event loop. Do not use `asyncio.gather()` with multiple harnesses that share a class — the second one will deadlock waiting for the first's lock.
- Two harnesses for **different App classes** can run concurrently in the same event loop without conflict.

## Time-Control Concurrency (`freeze_time` only)

`freeze_time` additionally uses a **process-global non-reentrant lock**. Only one harness at a time may hold the time lock in a process, regardless of which App class it tests.

- Sequential tests in the same worker are safe — the lock is released when the `async with` block exits cleanly.
- If two harnesses compete for the time lock, the second one raises `RuntimeError: freeze_time is already held by another harness`.

## Parallel Test Suites (pytest-xdist)

If you run tests with `pytest-xdist` (`pytest -n auto` or `pytest -n <N>`), two parallel workers can each try to acquire the time lock in their own processes — but because the lock is process-global, each worker's lock is independent. The problem is that two time-control tests scheduled to *different* workers can race on which one actually sees frozen time for your assertions.

Mark all tests that call `freeze_time` with the same `xdist_group` so they run on the same worker sequentially:

```python
--8<-- "pages/testing/snippets/testing_xdist_group.py"
```

If you run pytest sequentially (no `-n` flag), you do not need this marker.

## pytest-asyncio Mode

Configure `asyncio_mode = "auto"` in your `pyproject.toml`:

```toml
--8<-- "pages/testing/snippets/testing_asyncio_mode.toml"
```

With `asyncio_mode = "auto"`, any `async def test_*` function is automatically treated as an async test — no `@pytest.mark.asyncio` decorator required. If you skip this config, your async tests will silently succeed **without actually running** — a silent false-green failure mode.

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

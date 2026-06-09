# Write Your First Test

Hassette ships a test harness that runs your app without a live HA instance. Simulate events, assert API calls, control time.

## What You'll Learn

- Set up the test harness
- Seed entity state before a test
- Simulate a state change through the bus
- Assert your app called the right service

## Install

```bash
--8<-- "pages/testing/snippets/testing_install_pip.sh"
```

Or with uv:

```bash
--8<-- "pages/testing/snippets/testing_install_uv.sh"
```

Add this to your `pyproject.toml`:

```toml
--8<-- "pages/testing/snippets/testing_asyncio_mode.toml"
```

`asyncio_mode = "auto"` tells pytest-asyncio to treat every `async def test_*` as an async test. Without it, async tests silently pass without running. This is the most common cause of false-green test suites.

## Write the Test

```python
--8<-- "pages/testing/snippets/testing_quick_start.py"
```

[`AppTestHarness`][hassette.test_utils.AppTestHarness] runs your app against a test environment. The harness wires in a `RecordingApi` automatically — it replaces the live HA connection and records every API call your app makes. You assert on those recordings via `harness.api_recorder`. The `config` dict maps to your `AppConfig` fields — the same keys you would set in `hassette.toml`.

```python
--8<-- "pages/testing/snippets/testing_quick_start.py:harness_setup"
```

The `async with` block handles the full app lifecycle: it calls `on_initialize()`, waits for all listeners to register with the bus (Hassette's event pub/sub system), then yields. When the block exits, the harness calls `on_shutdown()` and cancels any running tasks.

**`simulate_state_change()`** publishes a `state_changed` event through the bus and waits for all triggered handlers to finish before returning.

```python
--8<-- "pages/testing/snippets/testing_quick_start.py:simulate"
```

**`harness.api_recorder.assert_called()`** checks that your app called the named method at least once with the given kwargs. Extra kwargs in the recorded call are allowed. Only the specified kwargs need to match.

```python
--8<-- "pages/testing/snippets/testing_quick_start.py:assert_called"
```

If your handler reads entity state during handling (e.g., checking whether a light is already on before toggling it), seed it first with `harness.set_state()` before simulating the event. `set_state()` writes directly to the in-process entity state cache that `self.states` reads from, without publishing a bus event, so no handlers fire. Seed before you simulate.

```python
--8<-- "pages/testing/snippets/testing_seed_state.py:seed"
```

## Run It

```
pytest test_my_app.py -v
```

Expected output:

```
collected 1 item

test_my_app.py::test_light_turns_on_when_motion_detected PASSED

1 passed in 0.12s
```

## Next Steps

- [Test Harness Reference](harness.md): full `AppTestHarness` API — all simulate methods, all assert methods, error handling
- [Time Control](time-control.md): freeze or advance the scheduler clock to test delayed and recurring jobs
- [Concurrency & pytest-xdist](concurrency.md): parallel test execution with `pytest-xdist` and concurrent harness patterns
- [Factories](factories.md): factory functions for building test state dicts, events, and helper records

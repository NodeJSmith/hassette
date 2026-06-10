# Testing

AppDaemon has no official test harness. Testing AppDaemon apps means patching the `Hass` runtime, which is fragile and usually tests the mock rather than your code.

Hassette ships `hassette.test_utils` with `AppTestHarness`, a test harness that wires your app into a real Hassette environment. Because Hassette apps are async, tests are async too — test functions are declared `async def`, and that's the main difference from testing synchronous code. `RecordingApi` replaces the live Home Assistant connection, recording every API call your app makes so you can assert against it — it's available in tests as `harness.api_recorder`.

## Setup

**Install test dependencies:**

```bash
pip install pytest pytest-asyncio    # or: uv add --dev pytest pytest-asyncio
```

**Add `asyncio_mode = "auto"` to your `pyproject.toml`:**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

!!! warning "Don't skip this"
    `asyncio_mode = "auto"` tells pytest to actually run `async def` test functions. Without it, pytest skips the test body and reports a false pass. This is the most common setup mistake when migrating from AppDaemon.

**Seed state before simulating events.** `set_state()` and `simulate_state_change()` are harness methods — the full example below shows them in context. Call `set_state()` before `simulate_state_change()` for the same entity. Calling it afterward overwrites the simulated state with the seeded value, silently corrupting subsequent reads.

```python
--8<-- "pages/migration/snippets/testing_seed_order.py"
```

## What a Test Looks Like

Open the harness in an `async with` block, seed your state, fire an event, assert the API call.

```python
--8<-- "pages/migration/snippets/testing_hassette_example.py"
```

Run it with `pytest -v`. A passing test prints `PASSED`; if pytest reports 0 tests or skips the body, check that `asyncio_mode = "auto"` made it into `pyproject.toml`.

## Full Reference

The [Testing Your Apps](../testing/index.md) section covers the complete harness API: state seeding, event simulation, API call assertions, scheduler time control, and concurrency helpers.

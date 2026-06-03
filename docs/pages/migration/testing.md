# Testing

AppDaemon has no official test harness. Testing AppDaemon apps means patching the `Hass` runtime, which is fragile and usually tests the mock rather than your code.

Hassette ships `hassette.test_utils` with `AppTestHarness`, an async test harness that wires your app into a real Hassette environment. `RecordingApi` replaces the live Home Assistant connection, recording every API call your app makes so you can assert against it.

## Setup

**Add `asyncio_mode = "auto"` to your `pyproject.toml`:**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

!!! warning "Don't skip this"
    Without it, async tests silently pass without running. This is the most common setup mistake when migrating from AppDaemon.

**Seed state before simulating events.** Call `set_state()` before `simulate_state_change()` for the same entity. Calling it afterward overwrites the simulated state with the seeded value, silently corrupting subsequent reads.

```python
--8<-- "pages/migration/snippets/testing_seed_order.py"
```

## What a Test Looks Like

Open an `AppTestHarness` context manager, seed your state, fire an event, assert the API call.

```python
--8<-- "pages/migration/snippets/testing_hassette_example.py"
```

## Full Reference

The [Testing Your Apps](../testing/index.md) section covers the complete harness API: state seeding, event simulation, API call assertions, scheduler time control, and concurrency helpers.

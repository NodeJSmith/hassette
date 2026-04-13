# Testing

This page covers the key differences in the testing approach when migrating from AppDaemon to Hassette.

## The Mental Model Shift

AppDaemon has no official test harness. Testing AppDaemon apps typically means patching the `Hass` runtime, which is fragile and often ends up testing the mock rather than your code.

Hassette ships with `hassette.test_utils` — a first-class async test harness. Instead of patching a runtime, you open an `AppTestHarness` context manager: it wires your app class into a real (but test-grade) Hassette environment with a `RecordingApi` instead of a live Home Assistant connection.

The other shift is from synchronous to asynchronous tests. AppDaemon apps and tests are synchronous. Hassette apps are async, so your tests are async too. This is handled automatically by `pytest-asyncio`.

## asyncio_mode = "auto" (Required)

Add this to your `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

!!! warning "Don't skip this config"
    If you omit `asyncio_mode = "auto"`, async tests will silently succeed **without actually running** — a false-green failure mode that is especially hard to diagnose after migration. This is the most common setup mistake when migrating from AppDaemon.

## set_state() Order Matters

Call `set_state()` before `simulate_state_change()` for the same entity. Calling it afterward will overwrite the simulated state with the seeded value, silently corrupting subsequent reads.

```python
# Correct: seed first, simulate second
await harness.set_state("binary_sensor.motion", "off")
await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

# Wrong: set_state() after simulate_state_change() overwrites the simulated state
await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")
await harness.set_state("binary_sensor.motion", "off")  # clobbers the simulated state
```

## Full Reference

For the complete harness API — seeding state, simulating events, asserting API calls, scheduler time control, and more — see [Testing Your Apps](../testing/index.md).

## See Also

- [Testing Your Apps](../testing/index.md) — full test harness reference
- [Time Control](../testing/time-control.md) — freezing and advancing time in tests
- [Concurrency & pytest-xdist](../testing/concurrency.md) — parallel test execution

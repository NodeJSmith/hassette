# Test Your Automation

Write a pytest test for your Hassette app using `AppTestHarness`. The harness runs your app against a test-grade Hassette environment — no live Home Assistant required.

## The App Under Test

This recipe tests a motion-activated lights app. It turns on a configurable light whenever the motion sensor changes to `"on"`.

```python
--8<-- "pages/recipes/snippets/test_automation.py:app"
```

## The Test

```python
--8<-- "pages/recipes/snippets/test_automation.py:test"
```

## How It Works

- **`AppTestHarness`** wires your app class into a test-grade Hassette environment with a `RecordingApi` in place of a live HA connection.
- **`async with`** starts the harness and calls your app's `on_initialize()`. Everything is torn down cleanly when the block exits.
- **`simulate_state_change()`** publishes a `state_changed` event through the bus and waits for all triggered handlers to finish before returning.
- **`api_recorder.assert_called()`** passes if the method was called at least once with kwargs that match all specified values. Partial matching — extra kwargs in the recorded call are allowed.
- **`api_recorder.assert_not_called()`** asserts that a method was never called — useful for testing the no-op path.

## Variations

**Testing scheduled jobs** — use `harness.freeze_time()` and `harness.trigger_due_jobs()` to advance time and fire jobs that would be due:

```python
from whenever import Instant

async def test_reminder_fires_at_noon():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        harness.freeze_time(Instant.from_utc(2024, 6, 1, 11, 59, 0))
        harness.advance_time(minutes=1)
        await harness.trigger_due_jobs()
        harness.api_recorder.assert_called("call_service", domain="notify")
```

**Testing API calls with arguments** — assert on specific service call parameters:

```python
async def test_scene_activated():
    async with AppTestHarness(SceneApp, config={}) as harness:
        await harness.simulate_state_change("input_boolean.movie_mode", old_value="off", new_value="on")
        harness.api_recorder.assert_called(
            "call_service", domain="scene", service="turn_on", target={"entity_id": "scene.movie"}
        )
```

## See Also

- [Testing Your Apps](../testing/index.md) — full reference for `AppTestHarness`, state seeding, and the recorder API
- [Time Control](../testing/time-control.md) — freeze and advance time for scheduler tests

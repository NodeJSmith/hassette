---
task_id: "T02"
title: "Add lifecycle completion event to DurationTimer and update duration tests"
status: "done"
depends_on: []
implements: ["FR#2", "FR#3", "AC#2", "AC#3"]
---

## Target Files

- modify: `src/hassette/bus/duration_timer.py`
- modify: `tests/integration/bus/conftest.py`
- modify: `tests/integration/bus/test_bus_duration.py`
- modify: `tests/integration/bus/CLAUDE.md`
- modify: `tests/unit/bus/test_duration_timer.py` — regression test added during the spec fix loop for a restart-while-active race condition

## Prompt

### Part A: DurationTimer.completed event

In `src/hassette/bus/duration_timer.py`, add a `completed` attribute to `DurationTimer.__init__()`:

```python
self.completed = asyncio.Event()
```

Modify `start()`: clear the event AFTER the internal `self.cancel()` call (which sets the old `completed`), not before it. Place the clear after the `self._cancelled = False` line:

```python
def start(self, on_fire, override_duration=None):
    if self._task and not self._task.done():
        self.cancel()          # sets the OLD completed event
    self._cancelled = False
    self.completed = asyncio.Event()  # fresh event for the NEW cycle
    ...
```

Modify `delayed_fire()` (the inner async function in `start()`): set `self.completed` at the very end, after the handler fires or after the guard-skip return. Both paths (normal fire and cancelled-guard skip) should set it. Structure:

```python
async def delayed_fire() -> None:
    try:
        await asyncio.sleep(sleep_duration)
    except asyncio.CancelledError:
        self.completed.set()
        return
    if self._cancelled:
        self.completed.set()
        return
    self._task = None
    self._started = False
    if self._cancel_sub is not None:
        self._cancel_sub.cancel()
        self._cancel_sub = None
    await on_fire()
    self.completed.set()
```

Modify `cancel()`: set `self.completed` at the end of the method (after all cleanup):

```python
def cancel(self) -> None:
    # ... existing code ...
    self._started = False
    self.completed.set()
```

### Part B: Increase DURATION

In `tests/integration/bus/conftest.py`, change:
```python
DURATION = 0.05  # 50 ms — fast enough for tests
```
to:
```python
DURATION = 0.2  # 200 ms — wide enough for CI scheduling jitter
```

### Part C: Update cancellation tests

In `tests/integration/bus/test_bus_duration.py`, update tests that assert "timer did NOT fire" to use the `completed` event instead of `asyncio.sleep(DURATION + margin)`.

To access the timer, add a helper at the top of the test file:

```python
from hassette.types import Topic

def get_duration_timer(harness: HassetteHarness, entity_id: str):
    """Get the DurationTimer for the first duration-enabled listener on an entity."""
    topic = f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}"
    for listener in harness.bus_service.router.get_topic_listeners(topic):
        if listener.duration_config and listener.duration_config.timer:
            return listener.duration_config.timer
    return None
```

Update these tests:

1. **`test_duration_cancelled_on_state_exit`** (line 55): After sending the cancel event, await `timer.completed` instead of `asyncio.sleep(DURATION + 0.1)`:
   ```python
   timer = get_duration_timer(harness, "light.kitchen")
   await asyncio.wait_for(timer.completed.wait(), timeout=2.0)
   assert received == []
   ```

2. **`test_duration_double_check_before_fire`** (line 118): This test manipulates StateProxy directly to make the re-check fail. Keep the `asyncio.sleep(DURATION * 0.8)` (now 160ms — generous) but replace the final `asyncio.sleep(DURATION * 0.4)` with awaiting `timer.completed`:
   ```python
   timer = get_duration_timer(harness, "light.kitchen")
   await asyncio.wait_for(timer.completed.wait(), timeout=2.0)
   assert received == []
   ```

3. **`test_duration_subscription_cancel_stops_timer`** (line 224): After `sub.cancel()`, await `timer.completed` instead of `asyncio.sleep(DURATION + 0.1)`:
   ```python
   timer = get_duration_timer(harness, "light.kitchen")
   sub.cancel()
   await asyncio.wait_for(timer.completed.wait(), timeout=2.0)
   assert received == []
   ```

4. **`test_changed_from_with_duration_cancels_on_revert`** (line 504): After the revert event, await `timer.completed`:
   ```python
   timer = get_duration_timer(harness, "door.front")
   await asyncio.wait_for(timer.completed.wait(), timeout=2.0)
   assert len(received) == 0
   ```

5. **`test_duration_with_once_fires_exactly_once`** (line 149): The second-trigger assertion at line 178 uses `asyncio.sleep(DURATION + 0.1)` to check no second fire — keep it (it's testing that a removed listener doesn't fire, not timer lifecycle).

6. **`test_duration_once_removal_on_exception`** (line 183): Same as above — the second-trigger sleep at line 219 tests removed-listener behavior, not timer lifecycle. Keep it.

7. **`test_duration_cancel_listener_same_owner_id`** (line 360): The `asyncio.sleep(0.02)` calls (lines 375, 388) are waiting for listener registration and cleanup, not timer lifecycle. Keep them but they're now proportionally fine with `DURATION=0.2`.

Leave positive-case tests (those that `await fired.wait()`) unchanged — they're already event-gated.

### Part D: Update CLAUDE.md

In `tests/integration/bus/CLAUDE.md`, update the documented `DURATION` value from `0.05` (50ms) to `0.2` (200ms).

## Verify

- [ ] FR#2: `DurationTimer` has a `completed` asyncio.Event that is set on fire, cancel, and guard-skip
- [ ] FR#3: `DURATION` is 0.2 in `conftest.py`
- [ ] AC#2: Cancellation tests use `timer.completed.wait()` instead of `asyncio.sleep`
- [ ] AC#3: `uv run pytest --count=20 -x tests/integration/bus/test_bus_duration.py` passes all 20 iterations
- [ ] `tests/integration/bus/CLAUDE.md` reflects the new DURATION value

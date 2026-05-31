---
task_id: "T02"
title: "Remove App.send_event and AppSync.send_event_sync"
status: "planned"
depends_on: ["T01"]
implements: ["FR#5", "FR#7", "AC#3", "AC#8"]
---

## Summary

Delete the legacy `App.send_event` and `AppSync.send_event_sync` methods now that `Bus.emit` exists. Also add a test proving self-delivery works (an app that emits and subscribes to the same topic receives its own event). This is the breaking change that locks in the new API surface.

## Prompt

1. **Delete `App.send_event`** in `src/hassette/app/app.py` (lines 135-137):
   ```python
   async def send_event(self, event: Event[Any]) -> None:
       """Send an event to the event bus."""
       await self.hassette.send_event(event)
   ```

2. **Delete `AppSync.send_event_sync`** in `src/hassette/app/app.py` (lines 154-156):
   ```python
   def send_event_sync(self, event: Event[Any]) -> None:
       """Synchronous version of send_event."""
       self.task_bucket.run_sync(self.send_event(event))
   ```

3. **Remove unused imports** — if `Event` and `Any` are no longer needed in `app.py` after deletion, remove them from the imports.

4. **Write tests** in `tests/integration/bus/test_bus_emit.py` (or add to the file from T01):
   - Test that an `App` instance has no `send_event` attribute (`assert not hasattr(app, 'send_event')`).
   - Test self-delivery: an app that subscribes to "test.self" and calls `bus.emit("test.self", data)` receives its own event in the handler.

5. **Run the full test suite** (`timeout 300 uv run nox -s dev -- -n 2`) to confirm nothing breaks. The internal `hassette.send_event` primitive is unchanged — all ~26 internal callers and all existing tests that use it should pass without modification.

## Focus

- `Event` import in `app.py` is also used by type annotations elsewhere in the file — check before removing.
- The `Any` import is likely still needed for other type hints in `app.py`.
- Self-delivery test: use the `hassette_with_bus` fixture. Register a handler with `bus.on(topic="test.self", handler=mock, name="self_test")`, then call `bus.emit("test.self", data)`, and assert the mock was called with the expected event.
- No `__getattr__` migration hint — a bare `AttributeError` is acceptable per the design decision.

## Verify

- [ ] FR#5: `App.send_event` and `AppSync.send_event_sync` no longer exist in `app.py`
- [ ] FR#7: An app that emits and subscribes to the same topic receives its own broadcast
- [ ] AC#3: Accessing `send_event` on an App instance raises `AttributeError`
- [ ] AC#8: Self-delivery test passes — handler fires for app's own emit

---
task_id: "T01"
title: "Add Bus.emit method and D.EventData accessor"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#6", "AC#1", "AC#2", "AC#4", "AC#5"]
---

## Summary

Add the core `Bus.emit(topic, data)` method and the `D.EventData[T]` DI accessor. This is the foundational task — it adds the new API surface that all other tasks build on. Also updates the codegen BUS_HEADER and regenerates the sync facade so `self.bus.sync.emit` works.

## Prompt

1. **Add `D.EventData[T]` to `src/hassette/event_handling/dependencies.py`:**

   ```python
   EventData: TypeAlias = Annotated[
       R,
       AnnotationDetails(ensure_present(A.get_path("payload.data"))),
   ]
   ```

   Add a docstring showing usage: `D.EventData[MyData]` extracts `event.payload.data` as `MyData`.

2. **Add `Bus.emit` to `src/hassette/bus/bus.py`:**

   At the top of the file (after existing TypeVars), declare:
   ```python
   EmitDataT = TypeVar("EmitDataT")
   ```

   Add the method to `Bus` (after `remove_all_listeners` / before the internal methods):
   ```python
   async def emit(self, topic: str, data: EmitDataT) -> None:
       payload = HassettePayload(data=data)
       event = Event(topic=topic, payload=payload)
       await self.hassette.send_event(event)
   ```

   Add a one-liner docstring: "Broadcast an event to all subscribers of the given topic."

3. **Update `BUS_HEADER` in `codegen/src/hassette_codegen/sync_facade/generic.py`:**

   In the imports block (line 107), add `TypeVar` to the `from typing import` line. After the imports block (before the `if typing.TYPE_CHECKING:` guard), add:
   ```python
   EmitDataT = TypeVar("EmitDataT")
   ```

4. **Regenerate the sync facade:**
   ```bash
   uv run python -m hassette_codegen.sync_facade
   ```
   Verify the generated `src/hassette/bus/sync.py` includes an `emit` method.

5. **Write integration tests** in `tests/integration/bus/test_bus_emit.py`:
   - Test that `bus.emit("test.topic", data)` delivers the event to a subscriber handler.
   - Test that a subscriber annotated with `D.EventData[SomeData]` receives the typed data.
   - Test that `bus.sync.emit("test.topic", data)` delivers from a sync context (use `task_bucket.run_sync` in the test or a sync fixture).

6. **Run Pyright** to confirm no type errors on the new method and its callers.

## Focus

- `EmitDataT` must be declared in `bus.py` locally — do NOT import `DataT` from `events/base.py` (it's covariant, would fail at parameter position).
- The `BUS_HEADER` update is mandatory before running codegen — without it, the generated sync.py will have a `NameError` at import time.
- Existing bus integration tests use the `hassette_with_bus` fixture from `tests/integration/conftest.py` — follow that pattern.
- `HassettePayload` and `Event` imports in `bus.py`: use `from hassette.events.base import Event, HassettePayload`.
- The `R` TypeVar already exists in `dependencies.py` (line 82) — reuse it for `EventData`.

## Verify

- [ ] FR#1: `bus.emit("topic", data)` wraps data in HassettePayload + Event and delivers to subscribers
- [ ] FR#2: A handler annotated with `D.EventData[SomeData]` receives the pre-extracted typed data
- [ ] FR#3: `bus.emit` is async and must be awaited
- [ ] FR#4: Pyright infers the correct type at the emit call site (EmitDataT flows through)
- [ ] FR#6: `bus.sync.emit("topic", data)` works from synchronous code
- [ ] AC#1: Calling `self.bus.emit("test.topic", SomeData(...))` delivers to all subscribers
- [ ] AC#2: Subscriber extracts `SomeData` via `D.EventData[SomeData]`
- [ ] AC#4: `self.bus.sync.emit("topic", data)` blocks until sent
- [ ] AC#5: Pyright reports no type errors on the new method

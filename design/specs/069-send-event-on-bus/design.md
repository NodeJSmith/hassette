# Design: Bus.emit — ergonomic inter-app broadcast

**Date:** 2026-05-31
**Status:** approved
**Scope-mode:** hold
**Research:** design/specs/069-send-event-on-bus/brief.md

## Problem

Broadcasting a message from one app to another requires constructing a framework envelope (`HassettePayload` + `Event`) and calling a method on `App` rather than `Bus`. This breaks the on/emit symmetry users expect from event bus APIs and forces boilerplate on every send call. The migration docs also incorrectly state that inter-app communication is "not supported."

## Goals

- Broadcast between apps via `self.bus.emit(topic, data)` with zero envelope boilerplate.
- On/emit symmetry: subscribe and publish live on the same object.
- Type safety at both ends: sender's data type is preserved via TypeVar; receiver extracts the same type via DI.
- Clean removal of `App.send_event` — no deprecation shim, no parallel path.
- Documentation that teaches the broadcast pattern and disambiguates from `fire_event`.

## Non-Goals

- Targeted/scoped sends (send to a specific app). Broadcast-to-all is the model; point-to-point is DI (#756).
- Schema enforcement on broadcast payloads. Broadcast is loose-coupled by design.
- Persistence or replay of events across reloads. Events are ephemeral.
- Migrating internal `hassette.send_event` callers to Bus. They stay on the internal primitive.
- Typed emit helpers (e.g., `emit_state_change`). The subscribe side needs helpers because subscribing requires topic knowledge; the emit side doesn't — `emit(topic, data)` is already the simple case.
- Framework-level `exclude_self` on emit. Requires carrying sender identity through the event stream protocol to BusService dispatch — non-trivial. Deferred to a follow-up issue. The handler-side guard pattern covers the use case for now.

## User Scenarios

### App Author: Automation developer

- **Goal:** Signal other apps when something happens (e.g., lights synced, motion detected).
- **Context:** During normal app operation, after completing an action that other apps may want to react to.

#### Broadcast a custom event

1. **Define a data class for the payload**
   - Sees: nothing — this is code-time
   - Decides: what fields to include
   - Then: frozen dataclass ready to use

2. **Call self.bus.emit(topic, data)**
   - Sees: IDE autocomplete on `self.bus.emit`
   - Decides: topic string and data to send
   - Then: event delivered to all subscribers of that topic

3. **Subscribe in another app**
   - Sees: handler fires with typed data via DI
   - Decides: what to do with the data
   - Then: action taken

#### Broadcast from synchronous code (AppSync)

1. **Call self.bus.sync.emit(topic, data)**
   - Sees: same API as async, via the `.sync` facade
   - Then: blocks until the event is sent

## Functional Requirements

- **FR#1** The event bus accepts a topic string and arbitrary typed data, wraps it in the framework's event envelope, and delivers it to all subscribers of that topic.
- **FR#2** A dependency injection accessor exists that extracts the typed data from a broadcast event's envelope, allowing subscribers to declare their handler parameter with a type annotation and receive the data pre-extracted.
- **FR#3** Emitting an event is an asynchronous operation.
- **FR#4** The data type passed by the sender is preserved through the system so that the receiver can extract it with type information.
- **FR#5** The legacy send method on the app base class is removed entirely — no deprecation period, no delegate.
- **FR#6** A synchronous equivalent of emit is available for apps that run in synchronous mode, accessible via the same bus object.
- **FR#7** An app that both emits and subscribes to the same topic receives its own broadcast. This is documented behavior, not a bug.

## Edge Cases

- **Self-delivery:** An app that emits on a topic it also subscribes to will receive its own event. Documented with a warning and a handler-side guard pattern (`if data.source == self.instance_name: return`). A framework-level `exclude_self` parameter is deferred — it requires stream protocol changes to carry sender identity through dispatch.
- **Emit during shutdown:** In normal shutdown, apps complete their shutdown hooks before streams close — so `emit` from `on_shutdown` succeeds. The silent-drop guard (`event_streams_closed`) exists as defense-in-depth for edge cases (dangling tasks, unexpected ordering), not as a user-facing scenario.
- **Empty data:** `emit("topic", None)` is valid. `HassettePayload[None]` is a legal generic instantiation.

## Acceptance Criteria

- **AC#1** Calling `self.bus.emit("test.topic", SomeData(...))` delivers an `Event[HassettePayload[SomeData]]` to all handlers subscribed to `"test.topic"`.
- **AC#2** The subscriber can extract `SomeData` via dependency injection (`D.EventData[SomeData]`).
- **AC#3** `App.send_event` no longer exists — accessing it raises `AttributeError`.
- **AC#4** `self.bus.sync.emit("topic", data)` works from `AppSync` hooks (blocks until sent).
- **AC#5** Pyright reports no type errors on the new method and its callers.
- **AC#6** The docs site has a "Broadcasting Events" section on the Bus concept page explaining emit, self-delivery, and the distinction from `fire_event`.
- **AC#7** The migration page no longer says inter-app communication is "not supported."
- **AC#8** An app that subscribes to topic X and calls `emit` with topic X receives its own event in the subscribed handler.

## Key Constraints

- `Bus.emit` must NOT write to the event stream directly — it must delegate through `hassette.send_event(event)` to preserve the guards (streams-closed check, wire_services check). Bypassing would create an unguarded path that can write after shutdown.
- Do not add `emit_event(event)` — no named user caller exists; add it later if a real need emerges.

## Dependencies and Assumptions

- The sync facade codegen (`codegen/src/hassette_codegen/sync_facade/`) must be re-run after adding `emit` to Bus. It auto-generates `BusSyncFacade.emit`.
- `HassettePayload` remains generic over `DataT` (confirmed: `HassettePayload[DataT]` at `events/base.py:92`).
- The DI infrastructure (`AnnotationDetails` + `A.get_path` accessor + `AnnotationConverter`) supports adding new extractors without framework changes. `D.EventData[T]` is a new `TypeAlias` using existing machinery.

## Architecture

### D.EventData[T] accessor

Add a DI accessor to `src/hassette/event_handling/dependencies.py`:

```python
EventData: TypeAlias = Annotated[
    R,
    AnnotationDetails(ensure_present(A.get_path("payload.data"))),
]
```

This enables subscribers to declare `data: D.EventData[CalendarData]` and receive the typed data pre-extracted from `event.payload.data`. The existing `AnnotationConverter` handles the identity case (value already matches the declared type) as a no-op.

### Bus.emit implementation

Add a single async method to `Bus` (`src/hassette/bus/bus.py`):

```python
EmitDataT = TypeVar("EmitDataT")

async def emit(self, topic: str, data: EmitDataT) -> None:
    """Broadcast an event to all subscribers of the given topic.

    Constructs a HassettePayload + Event envelope and delivers it via the
    framework's event stream. All apps subscribed to `topic` (via `on()` or
    glob patterns) will receive the event.
    """
    payload = HassettePayload(data=data)
    event = Event(topic=topic, payload=payload)
    await self.hassette.send_event(event)
```

The method is ~4 lines. It delegates to `hassette.send_event(event)` which enforces the `wire_services()` and `event_streams_closed` guards at `core.py:399-406`.

### Deletion targets

- `App.send_event` at `app.py:135-137` — delete
- `AppSync.send_event_sync` at `app.py:154-156` — delete

### Sync facade

Before running codegen, update `BUS_HEADER` in `codegen/src/hassette_codegen/sync_facade/generic.py` to include `TypeVar` in its imports and declare `EmitDataT = TypeVar("EmitDataT")`. Without this, the generated `sync.py` references `EmitDataT` as an undefined name.

Then run:
```bash
uv run python -m hassette_codegen.sync_facade
```

This auto-generates `BusSyncFacade.emit` in `src/hassette/bus/sync.py` following the `task_bucket.run_sync(self._bus.emit(...))` pattern used by all other facade methods.

### Documentation changes

1. **`docs/pages/core-concepts/apps/index.md`** — Replace the "Sending Internal Events Between Apps" section (lines 133-139) to reference `self.bus.emit` instead of `self.send_event`.
2. **`docs/pages/core-concepts/apps/snippets/apps_send_event.py`** — Rewrite to use `self.bus.emit("lights_synced", LightsSyncedData(source=self.instance_name))`.
3. **`docs/pages/migration/index.md`** line 30 — Change "Not supported" to reference `self.bus.emit` for broadcast and DI (#756) for direct contracted interaction.
4. **`docs/pages/core-concepts/api/utilities.md`** — Add a note to the `fire_event` section distinguishing it from `bus.emit` (fire_event goes to HA; emit stays local).

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `App.send_event` (`app.py:135-137`) | `Bus.emit` | Delete outright |
| `AppSync.send_event_sync` (`app.py:154-156`) | `BusSyncFacade.emit` (codegen'd) | Delete outright |
| `apps_send_event.py` snippet | New snippet using `self.bus.emit` | Rewrite in place |

## Convention Examples

### Bus method structure (async, delegates to service)

**Source:** `src/hassette/bus/bus.py:244`

```python
async def on(
    self,
    *,
    topic: str,
    handler: "HandlerType",
    where: "Predicate | Sequence[Predicate] | None" = None,
    # ... options ...
    name: str | None = None,
    on_error: "BusErrorHandlerType | None" = None,
) -> Subscription:
    """Subscribe to an event topic with optional filtering and modifiers."""
    # ... builds listener, delegates to bus_service ...
```

`emit` follows the same pattern: async method on Bus, delegates to a service-layer call (`hassette.send_event`).

### Sync facade delegation pattern

**Source:** `src/hassette/bus/sync.py` (auto-generated)

```python
def on(self, *, topic: str, handler: "HandlerType", ...) -> Subscription:
    return self.task_bucket.run_sync(self._bus.on(topic=topic, handler=handler, ...))
```

Every async Bus method gets a sync wrapper via codegen. `emit` will follow the same pattern automatically.

### Current send_event usage (being replaced)

**Source:** `docs/pages/core-concepts/apps/snippets/apps_send_event.py`

```python
# Current (verbose):
payload = HassettePayload(data=LightsSyncedData(source=self.instance_name))
await self.send_event(Event(topic="lights_synced", payload=payload))

# New (ergonomic):
await self.bus.emit("lights_synced", LightsSyncedData(source=self.instance_name))
```

## Alternatives Considered

**Keep `App.send_event` as a delegate to `Bus.emit`** — Lower risk (no breaking change), but adds a third path alongside the internal primitive and Bus. The brief's challenge flagged this as lower-regret, but the maintainer chose the clean break: the bus surface is in heavy flux, `send_event` is barely documented, and the install base is < 5. Breaking now while migration cost is near-zero beats carrying a delegate.

**Add `emit_event(event)` as a raw escape hatch** — Mirrors how `on()` sits alongside `on_state_change()`. But no named user caller exists, and the use case (pre-built Event with custom event_id/time_fired) is speculative. YAGNI — add later if a real need emerges.

**Use `publish` or `send` instead of `emit`** — `publish` pairs with `subscribe`, but our subscribe side uses `on`, not `subscribe`. `send` implies a recipient. `emit` is the canonical pair for `on` (Node EventEmitter, Vue, Socket.io).

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/test_core.py:125` (`test_send_event_writes_to_stream`) — update to call `bus.emit` instead of `hassette.send_event` directly, or keep as-is (it tests the internal primitive which still exists).
- `tests/unit/core/test_shutdown_event_guard.py` — tests `hassette.send_event` guards. These stay unchanged (they test the primitive, not the user-facing API).
- `tests/integration/bus/test_bus_error_handler.py` — uses `hassette.send_event` to inject events. Stays unchanged.

### New Test Coverage

- **FR#1/AC#1** — Integration test: `bus.emit("topic", data)` results in an event arriving at a subscriber (HassetteHarness).
- **FR#2/AC#2** — Integration test: subscriber with `D.EventData[SomeData]` annotation receives typed data pre-extracted from the envelope.
- **FR#4/AC#5** — Pyright pass (no new test file needed; type checking catches this).
- **FR#5/AC#3** — Unit test: `App` instance has no `send_event` attribute.
- **FR#6/AC#4** — Integration test: `bus.sync.emit("topic", data)` delivers the event from a sync context.
- **FR#7/AC#8** — Integration test: an app that emits and subscribes to the same topic receives its own event.

### Tests to Remove

No tests to remove — existing tests exercise the internal `hassette.send_event` primitive which remains.

## Documentation Updates

| Artifact | Change |
|---|---|
| `docs/pages/core-concepts/apps/index.md` | Rewrite "Sending Internal Events Between Apps" section to use `self.bus.emit` |
| `docs/pages/core-concepts/apps/snippets/apps_send_event.py` | Rewrite snippet to use `self.bus.emit` |
| `docs/pages/migration/index.md` line 30 | Replace "Not supported" with reference to `self.bus.emit` (broadcast) and DI #756 (contracted) |
| `docs/pages/core-concepts/api/utilities.md` | Add disambiguation note: `fire_event` sends to HA; `bus.emit` stays local |
| CHANGELOG (via PR title) | `feat!: move inter-app broadcast to Bus.emit, remove App.send_event` |

## Impact

### Changed Files

| File | Change |
|---|---|
| `src/hassette/event_handling/dependencies.py` | Add `D.EventData[T]` accessor (~4 lines) |
| `src/hassette/bus/bus.py` | Add `emit` method (~10 lines) |
| `codegen/src/hassette_codegen/sync_facade/generic.py` | Add `TypeVar` import and `EmitDataT` to `BUS_HEADER` |
| `src/hassette/bus/sync.py` | Regenerated by codegen (adds `emit`) |
| `src/hassette/app/app.py` | Delete `send_event` (line 135-137) and `send_event_sync` (line 154-156) |
| `docs/pages/core-concepts/apps/index.md` | Rewrite section |
| `docs/pages/core-concepts/apps/snippets/apps_send_event.py` | Rewrite snippet |
| `docs/pages/migration/index.md` | Fix "not supported" line |
| `docs/pages/core-concepts/api/utilities.md` | Add disambiguation note |
| `tests/` (new files) | Integration tests for emit + sync.emit + self-delivery |

### Behavioral Invariants

- `hassette.send_event(event)` continues to work unchanged — all ~26 internal callers are unaffected.
- `Event.topic` remains the routing key used by `BusService.dispatch`.
- `HassettePayload.origin` stays fixed at `"HASSETTE"` — `emit` does not allow overriding it.
- All existing `bus.on(...)` subscriptions continue to receive events regardless of whether they were sent via the old `App.send_event` or the new `Bus.emit` (same underlying stream).

### Blast Radius

- **External users** — breaking change for anyone calling `App.send_event` (estimated: 0 users). Migration is mechanical: `self.send_event(event)` → `self.bus.emit(event.topic, event.payload.data)`.
- **Test harness** — `RecordingApi`/`HassetteHarness` don't expose `send_event` to test authors; no harness changes needed.
- **Codegen** — sync facade codegen must be re-run. `BUS_HEADER` in `generic.py` needs a `TypeVar` import and `EmitDataT` declaration added before regeneration.

## Open Questions

None — all resolved during brief exploration, challenge, and define phases.

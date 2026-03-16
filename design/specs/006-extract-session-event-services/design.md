# Design: Extract SessionManager and EventStreamService from Hassette Core

**Date:** 2026-03-16
**Status:** implemented
**Spec:** design/specs/006-extract-session-event-services/spec.md

## Problem

`Hassette` (`src/hassette/core/core.py`, 479 lines, 26 instance attributes) directly owns two unrelated subsystems:

1. **Session lifecycle** — database CRUD for session rows: creating, orphan-cleaning, crash-recording, and finalising. This is ~235 lines of methods + state that have no business being on the coordinator class.
2. **Event stream infrastructure** — the anyio memory channel that routes events from 5 producer services to the bus. Buffer size is hardcoded to `1000`; ownership is tangled between Hassette (creation and teardown) and `HassetteHarness` (manual stream management in tests).

Both extractions are part of ADR-0002 (phases 1 and 2). The code is already logically isolated within Hassette — extraction is mechanical, not redesign.

## Non-Goals

- AppHandler refactor (ADR-0002 phase 3, tracked as #328)
- Changing the session schema or data model
- Updating the 5 event producer services to accept `EventStreamService` directly (delegation through `Hassette.send_event()` is sufficient)
- Any new user-facing features beyond configurable buffer size
- Performance improvements beyond what configurable buffer size enables

## Architecture

### Phase 1: SessionManager (`src/hassette/core/session_manager.py`)

`SessionManager` is a `Resource` (no background task, so not a `Service`). It extracts the following from `Hassette`:

**State moved from `Hassette.__init__`:**
- `_session_id: int | None`
- `_session_error: bool`
- `_session_lock: asyncio.Lock`

**Methods extracted (4 public + 4 DB-worker pairs):**
- `create_session()` / `_do_create_session()` — inserts session row, stores ID
- `mark_orphaned_sessions()` / `_do_mark_orphaned_sessions()` — marks prior "running" sessions as "unknown"
- `on_service_crashed(event)` / `_do_on_service_crashed(event)` — updates session row on crash
- `finalize_session()` / `_do_finalize_session()` — writes final status and `stopped_at`

`SessionManager` receives `DatabaseService` via constructor injection. It exposes a `session_id` property that raises `RuntimeError` if no session has been created yet (identical behaviour to current Hassette).

**Constructor signature:**
```python
class SessionManager(Resource):
    def __init__(
        self,
        hassette: "Hassette",
        *,
        database_service: "DatabaseService",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._database_service = database_service
        self._session_id: int | None = None
        self._session_error: bool = False
        self._session_lock = asyncio.Lock()
```

**Registration in `Hassette.__init__`** — after `_database_service`:
```python
self._database_service = self.add_child(DatabaseService)
self._session_manager = self.add_child(SessionManager, database_service=self._database_service)
```

**Hassette changes:**
- `session_id` property becomes a one-liner delegating to `self._session_manager.session_id`
- `run_forever()` callsites updated: `self._mark_orphaned_sessions()` → `self._session_manager.mark_orphaned_sessions()`, `self._create_session()` → `self._session_manager.create_session()`, crash handler → `self._session_manager.on_service_crashed`
- `before_shutdown()` callsite: `self._finalize_session()` → `self._session_manager.finalize_session()`
- All session methods and state removed from `Hassette` (~235 lines reduction)

**`DatabaseService` and `CommandExecutor`** are untouched — both access `self.hassette.session_id`, which continues to work through the delegating property.

**Test impact:** `test_session_lifecycle.py` currently uses the unbound-method trick (`Hassette._create_session(mock_hassette)`). After extraction, tests construct a real `SessionManager` with a test `DatabaseService` and call methods directly — simpler and more conventional. Tests move to `tests/integration/test_session_manager.py`. The `create_session_manager(db_service)` fixture lives in `conftest.py`.

### Phase 2: EventStreamService (`src/hassette/core/event_stream_service.py`)

`EventStreamService` is a `Resource` (no `serve()` loop needed — the streams are synchronously created and the lifecycle is pure `on_shutdown` teardown).

**Code extracted from `core.py`:**
- Stream creation: `create_memory_object_stream[tuple[str, Event[Any]]](buffer_size)` — buffer size now reads from `hassette.config.hassette_event_buffer_size`
- `send_event(event_name, event)` method
- `event_streams_closed` property
- Stream teardown in `on_shutdown()`

**Service shape:**
```python
class EventStreamService(Resource):
    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        buffer_size = hassette.config.hassette_event_buffer_size
        self._send_stream, self._receive_stream = create_memory_object_stream(buffer_size)

    @property
    def receive_stream(self):
        return self._receive_stream

    async def send_event(self, event_name: str, event: "Event[Any]") -> None:
        await self._send_stream.send((event_name, event))

    @property
    def event_streams_closed(self) -> bool:
        return self._send_stream._closed and self._receive_stream._closed

    async def on_shutdown(self) -> None:
        await self._send_stream.aclose()
        await self._receive_stream.aclose()
```

**Critical ordering constraint:** `EventStreamService` must be registered as the **first** `add_child()` call in `Hassette.__init__`, before `DatabaseService`. This is because `BusService` receives `receive_stream.clone()` at construction time (via `add_child(BusService, stream=...)`), so the stream must exist before `BusService` is registered.

**Registration in `Hassette.__init__`:**
```python
self._event_stream_service = self.add_child(EventStreamService)  # FIRST — stream must exist before BusService
self._database_service = self.add_child(DatabaseService)
# ...
self._bus_service = self.add_child(
    BusService,
    stream=self._event_stream_service.receive_stream.clone(),
    executor=self._command_executor,
)
```

**Hassette changes:**
- `_send_stream` and `_receive_stream` instance variables removed
- `event_streams_closed` delegates: `return self._event_stream_service.event_streams_closed`
- `send_event()` delegates: `await self._event_stream_service.send_event(event_name, event)`
- Stream teardown in `on_shutdown()` removed (handled by `EventStreamService.on_shutdown()`)

**Producer services — no changes.** All 5 producers (`AppHandler`, `WebsocketService`, `FileWatcherService`, `ServiceWatcher`, `AppLifecycleManager`) call `self.hassette.send_event(...)` — the delegating method on Hassette means zero producer changes.

**BusService — no changes.** Its constructor already accepts `stream` as a kwarg; only the caller (`Hassette.__init__`) changes the source of the stream.

### Config field addition

Add to `HassetteConfig` in `src/hassette/config/`:
```python
hassette_event_buffer_size: int = Field(default=1000)
"""Buffer capacity of the internal anyio memory channel used to route events to the bus."""
```

The default of `1000` preserves current behaviour.

### HassetteHarness update

`HassetteHarness._start_bus()` currently manually creates streams and assigns them to `hassette._send_stream` / `hassette._receive_stream`, with `exit_stack` callbacks for teardown. After Phase 2, this must be updated to:

1. Create a real `EventStreamService` child on the mock hassette
2. Pass `receive_stream.clone()` to `BusService` as before
3. Remove the manual `exit_stack.push_async_callback(stream.aclose)` calls — `EventStreamService.on_shutdown()` handles teardown

`_HassetteMock.send_event()` and `_HassetteMock.event_streams_closed` must delegate to the `EventStreamService` instance (or be removed in favour of the real service).

## Alternatives Considered

**Constructor injection for producers (rejected):** The spec originally called for all 5 producer services to receive `EventStreamService` via constructor. The research confirmed that `Hassette.send_event()` delegation achieves the same decoupling with zero changes to producers. Constructor injection can be added in a future phase if direct dependency clarity becomes important; it is not worth the churn now.

**`EventStreamService` as `Service` subclass (rejected):** `Service` requires a `serve()` loop. The streams have no background behaviour — they're created synchronously and torn down in `on_shutdown`. Using `Resource` is correct and avoids a spurious empty `serve()` method.

**Extracting buffer size without `EventStreamService` (not considered):** Configuring the buffer size is only meaningful if `EventStreamService` owns the stream creation. Doing it independently would require patching `core.py` and would miss the point of the extraction.

## Open Questions

None — research and planning interrogation resolved all outstanding items.

## Impact

**New files:**
- `src/hassette/core/session_manager.py`
- `src/hassette/core/event_stream_service.py`
- `tests/integration/test_session_manager.py`
- `tests/integration/test_event_stream_service.py`

**Modified files:**
- `src/hassette/core/core.py` — ~235 line reduction (session), stream removal, delegating wrappers
- `src/hassette/config/*.py` — add `hassette_event_buffer_size` field
- `src/hassette/testing/harness.py` — update `_start_bus()`, `_HassetteMock` stream handling
- `tests/conftest.py` — add `create_session_manager()` and `create_event_stream_service()` fixtures
- `tests/integration/test_session_lifecycle.py` — migrate to use `SessionManager` directly

**Untouched:**
- All 5 producer services
- `BusService`
- `DatabaseService`
- `CommandExecutor`
- All existing tests (intent preserved, infrastructure updated)

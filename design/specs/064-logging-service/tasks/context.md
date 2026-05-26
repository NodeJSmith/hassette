# Context: Logging Service

## Problem & Motivation
The logging infrastructure operates outside the Resource lifecycle — module-level globals, late-wiring `set_database()`, and manual `before_shutdown()` cleanup instead of proper dependency-graph-driven initialization and shutdown. This makes logging a one-off exception that resists refactoring and blocks future work requiring logging-service coordination. Additionally, `insert_log_records` is misplaced on TelemetryRepository, forcing a cross-service traversal through `command_executor.repository`.

## Visual Artifacts
None.

## Key Decisions
1. LoggingService is a **Resource** (not Service) — the QueueListener manages its own background thread; no `serve()` or `RestartSpec` needed.
2. **Two-phase model**: `enable_basic_logging()` provides sync console logging before the Resource tree; `LoggingService.on_initialize()` upgrades to the full async pipeline.
3. **Resilient initialization**: The async pipeline (QueueListener + stream + capture) starts unconditionally. Only persistence handler creation is wrapped in error handling — if it fails, the pipeline runs without persistence.
4. **LogCaptureHandler created in `__init__()`** for instance stability — broadcast wiring from RuntimeQueryService survives any re-initialization.
5. **No module-level globals**: `_log_capture_handler`, `_log_persistence_handler`, `_queue_listener`, `get_log_capture_handler()`, `get_log_persistence_handler()`, `shutdown_logging()` are all removed. LoggingService is the single source of truth.
6. **`_insert_log_records` is private** on DatabaseService, matching the existing `_do_*`/`_check_*` convention. Only callable via `enqueue()`.
7. **Initialization ordering via `depends_on`** — services needing guaranteed async logging declare LoggingService in their depends_on.
8. **`enable_basic_logging()` returns the StreamHandler** — stored on Hassette, passed to LoggingService via constructor injection.
9. **Defensive cleanup guard** at the start of `on_initialize()` — removes stale QueueHandler instances and stops any running QueueListener (idempotent).
10. **QueueListener.stop() via `asyncio.to_thread()` with 5s timeout** in on_shutdown() — prevents sentinel blocking from stalling the event loop.

## Constraints & Anti-Patterns
- The sync→async swap must NOT lose records. Add QueueHandler before removing StreamHandler.
- `enable_basic_logging()` must NOT reference DatabaseService, LoggingService, or any Resource.
- LoggingService must NOT depend on RuntimeQueryService (would create a cycle).
- Do NOT add module-level globals or accessors — they are being eliminated.
- Do NOT make `_insert_log_records` public — matches existing private write coroutine pattern.
- Do NOT use `from __future__ import annotations`.
- Do NOT use `Optional[X]` — use `X | None`.

## Design Doc References
- `## Architecture` — full two-phase model, class structure, wiring details
- `## Replacement Targets` — table of what's being removed/moved
- `## Edge Cases` — force-terminate, sentinel blocking, degraded mode, test isolation
- `## Key Constraints` — non-negotiable rules
- `## Test Strategy` — existing tests to adapt, new coverage, logging_pipeline fixture

## Convention Examples

### Resource with constructor injection (SessionManager pattern)

**Source:** `src/hassette/core/session_manager.py`

```python
class SessionManager(Resource):
    bus: Bus

    def __init__(
        self,
        hassette: "Hassette",
        *,
        database_service: "DatabaseService",
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._database_service = database_service
        self.bus = self.add_child(Bus)
        self._session_id: int | None = None
        self._session_lock = asyncio.Lock()

    async def on_initialize(self) -> None:
        self.bus.on(...)
        self.mark_ready(reason="SessionManager initialized")
```

### Service with depends_on and lifecycle

**Source:** `src/hassette/core/command_executor.py`

```python
class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
    )

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue(maxsize=hassette.config.database.telemetry_write_queue_max)
        self.repository = TelemetryRepository(hassette.database_service)
```

### DatabaseService.enqueue() for fire-and-forget writes

**Source:** `src/hassette/core/database_service.py`

```python
def enqueue(self, coro: Coroutine[Any, Any, Any]) -> bool:
    """Submit a coroutine for fire-and-forget execution."""
    if self._db_write_queue is None:
        coro.close()
        raise RuntimeError("DatabaseService.enqueue() called before on_initialize()")
    try:
        self._db_write_queue.put_nowait((coro, None))
    except asyncio.QueueFull:
        coro.close()
        self.logger.error("DB write queue full (%d items) — dropping", self._db_write_queue.qsize())
        return False
    return True
```

### Wiring services with constructor injection in wire_services()

**Source:** `src/hassette/core/core.py`

```python
self._session_manager = self.add_child(SessionManager, database_service=self._database_service)
```

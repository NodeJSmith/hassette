# Implementation Plan: FastAPI Backend and Data Sync Service

## 1. Summary

Add a FastAPI-based HTTP/WebSocket backend and a DataSyncService to hassette. These new services expose REST endpoints and a real-time WebSocket channel that a future web UI can consume. The design follows hassette's existing patterns: the Resource/Service hierarchy for lifecycle management, the Bus for event subscriptions, StateProxy for cached entity state, and pydantic-settings for configuration.

---

## 2. Architectural Decisions

### 2.1 Replace HealthService with FastAPI

**Decision: Remove the existing aiohttp-based HealthService entirely and replace it with a FastAPI-based WebApiService that subsumes the `/healthz` endpoint alongside the new web UI endpoints.**

Rationale:

- The existing `HealthService` (`src/hassette/core/health_service.py`) is a minimal aiohttp server with a single `/healthz` endpoint and a workaround for aiohttp's frame inspection bugs (`MyAppKey` subclass). It was never a robust solution.
- FastAPI provides automatic OpenAPI docs, pydantic model serialization (matching hassette's pydantic-first philosophy), native WebSocket support, and dependency injection -- all superior for a rich API surface.
- Replacing rather than running alongside avoids two HTTP servers on different ports, simplifies configuration (one set of host/port/log_level fields instead of two), and removes the aiohttp web server dependency (aiohttp remains as a client library for `WebsocketService`).
- The `/healthz` endpoint is preserved as a FastAPI route so existing Docker healthcheck configurations continue to work with only a port change (or no change if the user configures `web_api_port` to match the old `health_service_port`).

### 2.2 Where New Services Live in the Resource Hierarchy

The new services replace `HealthService` and are children of `Hassette` (the root Resource), just like `BusService`, `WebsocketService`, and `AppHandler`.

```
Hassette (root Resource)
  +-- BusService
  +-- WebsocketService
  +-- AppHandler
  +-- StateProxy
  +-- ...existing services...
  +-- DataSyncService      (NEW -- Resource, replaces nothing)
  +-- WebApiService        (NEW -- Service, replaces HealthService)
```

`DataSyncService` is a plain `Resource` (not `Service`) because it does not have a long-running `serve()` loop; it passively subscribes to Bus events and exposes query methods. `WebApiService` is a `Service` because it runs uvicorn in `serve()` until cancelled. It takes over the health-check responsibility from the removed `HealthService`.

### 2.3 Dependency Flow

```
WebApiService  -->  DataSyncService  -->  BusService
                                     -->  StateProxy
                                     -->  AppHandler (via registry)
```

`DataSyncService` must wait for `BusService`, `StateProxy`, and `AppHandler` to be ready before subscribing. `WebApiService` must wait for `DataSyncService` to be ready before starting the FastAPI server.

---

## 3. New Dependencies

Add to `pyproject.toml` `[project.dependencies]`:

```
"fastapi>=0.115.0",
"uvicorn[standard]>=0.34.0",
```

`uvicorn[standard]` includes `httptools` and `uvloop` (optional but beneficial). The bare `fastapi` package handles WebSocket natively since it is part of Starlette.

---

## 4. Configuration Changes

### Removed fields (from HealthService):

```python
run_health_service        # replaced by run_web_api
health_service_port       # replaced by web_api_port
health_service_log_level  # replaced by web_api_log_level
```

### New fields in `HassetteConfig` (`src/hassette/config/config.py`):

```python
# Web API configuration
run_web_api: bool = Field(default=True)
"""Whether to run the web API service (includes healthcheck and UI backend)."""

web_api_host: str = Field(default="0.0.0.0")
"""Host to bind the web API server to."""

web_api_port: int = Field(default=8126)
"""Port to run the web API server on."""

web_api_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
"""Logging level for the web API service."""

web_api_cors_origins: tuple[str, ...] = Field(
    default=("http://localhost:3000", "http://localhost:5173")
)
"""Allowed CORS origins for the web API, typically the UI dev server."""

web_api_event_buffer_size: int = Field(default=500)
"""Maximum number of recent events to keep in the DataSyncService ring buffer."""

web_api_log_buffer_size: int = Field(default=2000)
"""Maximum number of log entries to keep in the LogCaptureHandler ring buffer."""

web_api_job_history_size: int = Field(default=1000)
"""Maximum number of job execution records to keep."""
```

Note: `run_web_api` defaults to `True` (matching the old `run_health_service` default) and `web_api_port` defaults to `8126` (matching the old `health_service_port` default) so existing Docker healthcheck configurations continue to work without changes.

TOML example (`hassette.toml`):

```toml
[hassette]
run_web_api = true
web_api_port = 8126
web_api_cors_origins = ["http://localhost:3000"]
```

---

## 5. New File Layout

```
src/hassette/
  core/
    data_sync_service.py      # DataSyncService resource
    web_api_service.py         # WebApiService (Service subclass)
  web/
    __init__.py
    app.py                     # create_fastapi_app() factory
    dependencies.py            # FastAPI Depends() helpers
    models.py                  # Pydantic response models
    routes/
      __init__.py
      health.py                # GET /api/health, GET /healthz (backwards compat)
      entities.py              # GET /api/entities, /api/entities/{id}, /api/entities/domain/{domain}
      apps.py                  # GET/POST /api/apps, /api/apps/{key}, /api/apps/{key}/start|stop|reload
      services.py              # GET /api/services
      events.py                # GET /api/events/recent
      logs.py                  # GET /api/logs
      scheduler.py             # GET /api/scheduler/jobs, /api/scheduler/history
      config.py                # GET /api/config
      ws.py                    # WS /api/ws
tests/
  unit/core/
    test_data_sync_service.py
  integration/
    test_web_api.py
```

---

## 6. Component Designs

### 6.1 DataSyncService (`src/hassette/core/data_sync_service.py`)

Aggregates and caches system state for the web UI. Single source of truth that FastAPI endpoints query.

**Class structure:**

```python
class DataSyncService(Resource):
    bus: Bus
    _event_buffer: deque[dict]        # ring buffer of recent events
    _ws_clients: set[asyncio.Queue]   # per-websocket broadcast queues
    _lock: asyncio.Lock               # protects _ws_clients mutations
```

**Lifecycle:**

- `on_initialize()`: Waits for `BusService`, `StateProxy`, `AppHandler` to be ready. Then subscribes to:
  - `hass.event.state_changed` (all entities) -- appends to event buffer and broadcasts to WS clients
  - `hassette.event.app_state_changed` -- broadcasts app status changes
  - `hassette.event.service_status` -- broadcasts service lifecycle
  - `hassette.event.websocket_connected` / `hassette.event.websocket_disconnected` -- broadcasts connectivity
- `on_shutdown()`: Removes all bus listeners, closes all WS client queues.

**Key methods:**

```python
# Entity state access (delegates to StateProxy)
def get_entity_state(self, entity_id: str) -> HassStateDict | None
def get_all_entity_states(self) -> dict[str, HassStateDict]
def get_domain_states(self, domain: str) -> dict[str, HassStateDict]

# App status (delegates to AppHandler registry)
def get_app_status_snapshot(self) -> AppStatusSnapshot

# Event history
def get_recent_events(self, limit: int = 50) -> list[dict]

# System health
def get_system_status(self) -> dict

# WebSocket client management
async def register_ws_client(self) -> asyncio.Queue
def unregister_ws_client(self, queue: asyncio.Queue) -> None
async def broadcast(self, message: dict) -> None
```

The `broadcast()` method iterates `_ws_clients` and puts the message dict into each queue. If a queue is full (slow client), the message is dropped for that client with a warning.

Event handler methods follow this pattern:

```python
async def _on_state_change(self, event: RawStateChangeEvent) -> None:
    entry = {
        "type": "state_changed",
        "entity_id": event.payload.data.entity_id,
        "new_state": event.payload.data.new_state,
        "old_state": event.payload.data.old_state,
        "timestamp": ...,
    }
    self._event_buffer.append(entry)
    await self.broadcast(entry)
```

### 6.2 WebApiService (`src/hassette/core/web_api_service.py`)

Runs the FastAPI/uvicorn server.

```python
class WebApiService(Service):
    host: str
    port: int
    _server: uvicorn.Server | None
```

**Lifecycle:**

- `create()`: Reads `host` and `port` from config.
- `on_initialize()`: Waits for `DataSyncService` readiness, then calls `super().on_initialize()` which spawns `serve()`.
- `serve()`: Creates the FastAPI app via `create_fastapi_app(self.hassette)`, configures `uvicorn.Config` with `lifespan="off"` (hassette manages lifecycle, not uvicorn), then runs `uvicorn.Server.serve()`.
- `on_shutdown()`: Cancels the serve task, ensures uvicorn server is shut down cleanly.

**Registration in Hassette core (`core.py`):**

```python
self._data_sync_service = self.add_child(DataSyncService)
self._web_api_service = self.add_child(WebApiService)
```

Placed after `_state_proxy` and `_app_handler` so they initialize later in the startup sequence.

### 6.3 FastAPI Application Factory (`src/hassette/web/app.py`)

```python
def create_fastapi_app(hassette: Hassette) -> FastAPI:
    app = FastAPI(
        title="Hassette Web API",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.hassette = hassette

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(hassette.config.web_api_cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(entities_router, prefix="/api")
    app.include_router(apps_router, prefix="/api")
    app.include_router(services_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    app.include_router(logs_router, prefix="/api")
    app.include_router(scheduler_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(ws_router, prefix="/api")
    return app
```

### 6.4 FastAPI Dependency Injection (`src/hassette/web/dependencies.py`)

```python
from fastapi import Request

def get_hassette(request: Request) -> Hassette:
    return request.app.state.hassette

def get_data_sync(request: Request) -> DataSyncService:
    return request.app.state.hassette._data_sync_service

def get_api(request: Request) -> Api:
    return request.app.state.hassette.api
```

### 6.5 Response Models (`src/hassette/web/models.py`)

```python
class SystemStatusResponse(BaseModel):
    status: str                          # "ok" | "degraded" | "starting"
    websocket_connected: bool
    uptime_seconds: float | None
    entity_count: int
    app_count: int
    services_running: list[str]

class EntityStateResponse(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str | None
    last_updated: str | None

class EntityListResponse(BaseModel):
    count: int
    entities: list[EntityStateResponse]

class AppInstanceResponse(BaseModel):
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: str
    error_message: str | None = None

class AppStatusResponse(BaseModel):
    total: int
    running: int
    failed: int
    apps: list[AppInstanceResponse]
    only_app: str | None = None

class EventEntry(BaseModel):
    type: str
    entity_id: str | None = None
    timestamp: str
    data: dict[str, Any] = {}

class WsMessage(BaseModel):
    type: str                            # "state_changed", "app_status", "system_event"
    data: dict[str, Any]
```

### 6.6 Log Capture (`src/hassette/logging_.py` + `src/hassette/core/data_sync_service.py`)

App developers need to see their app's logs in the UI. Currently all logging goes to stdout via Python's `logging` module with no in-memory capture. We add a `logging.Handler` subclass that writes log records into a ring buffer on `DataSyncService`, and broadcasts them over the WebSocket.

**LogCaptureHandler** (lives in `src/hassette/logging_.py` alongside `enable_logging()`):

```python
class LogCaptureHandler(logging.Handler):
    """Captures log records into a bounded deque and broadcasts to WS clients."""

    _buffer: deque[LogEntry]
    _broadcast_fn: Callable[[dict], Awaitable[None]] | None
    _loop: asyncio.AbstractEventLoop | None

    def __init__(self, buffer_size: int = 2000):
        super().__init__()
        self._buffer = deque(maxlen=buffer_size)
        self._broadcast_fn = None
        self._loop = None

    def set_broadcast(self, fn: Callable[[dict], Awaitable[None]], loop: asyncio.AbstractEventLoop) -> None:
        """Called by DataSyncService after initialization to wire up WS broadcast."""
        self._broadcast_fn = fn
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        entry = LogEntry(
            timestamp=record.created,
            level=record.levelname,
            logger_name=record.name,
            func_name=record.funcName,
            lineno=record.lineno,
            message=self.format(record),
            exc_info=record.exc_text,
        )
        self._buffer.append(entry)
        if self._broadcast_fn and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._broadcast_fn({"type": "log", "data": entry.to_dict()}),
            )
```

The handler is installed in `enable_logging()` and attached to the `hassette` root logger, so it captures all hassette and app logs. `DataSyncService.on_initialize()` calls `set_broadcast()` to wire up real-time push to WebSocket clients.

**LogEntry dataclass** (lives in `src/hassette/logging_.py`):

```python
@dataclass
class LogEntry:
    timestamp: float              # Unix timestamp (time.time())
    level: str                    # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    logger_name: str              # e.g. "hassette.AppHandler.MyApp[0]"
    func_name: str                # Function name
    lineno: int                   # Line number
    message: str                  # Formatted message
    exc_info: str | None = None   # Exception traceback if present

    @property
    def app_key(self) -> str | None:
        """Extract app key from logger name if this is an app log.
        Logger names follow: hassette.AppHandler.<AppClass>[<index>]..."""
        ...

    def to_dict(self) -> dict: ...
```

The `logger_name` follows hassette's hierarchical naming convention, so the frontend can filter logs by:
- **App**: Filter on `logger_name` starting with the app's `unique_name`
- **Service**: Filter on service logger names (e.g. `hassette.BusService`)
- **Level**: Filter on `level` field

**DataSyncService integration:**

```python
# New attribute:
log_handler: LogCaptureHandler  # set during on_initialize()

# New method:
def get_recent_logs(self, limit: int = 100, app_key: str | None = None,
                    level: str | None = None) -> list[dict]:
    """Return recent log entries, optionally filtered by app or level."""
```

**Response model:**

```python
class LogEntryResponse(BaseModel):
    timestamp: float
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    exc_info: str | None = None
    app_key: str | None = None       # Extracted from logger_name if app log
```

### 6.7 Scheduler Global View (`src/hassette/core/scheduler_service.py`)

Each `Scheduler` instance belongs to a single app. There is no way to get a cross-app view of all scheduled jobs. The `SchedulerService` has the priority queue internally but no method to enumerate it. We add a `get_all_jobs()` method.

**Changes to `_ScheduledJobQueue`:**

```python
async def get_all(self) -> list[ScheduledJob]:
    """Return a snapshot of all queued jobs (non-destructive)."""
    async with self._lock:
        return list(self._queue._queue)  # shallow copy of the heap
```

**Changes to `SchedulerService`:**

```python
async def get_all_jobs(self) -> list[ScheduledJob]:
    """Return all currently scheduled jobs across all apps."""
    return await self._job_queue.get_all()
```

**DataSyncService integration:**

```python
async def get_scheduled_jobs(self) -> list[dict]:
    """Return all scheduled jobs across all apps, sorted by next_run."""
    jobs = await self.hassette._scheduler_service.get_all_jobs()
    return [
        {
            "job_id": job.job_id,
            "name": job.name,
            "owner": job.owner,
            "next_run": str(job.next_run),
            "repeat": job.repeat,
            "cancelled": job.cancelled,
            "trigger_type": type(job.trigger).__name__ if job.trigger else "once",
            "timeout_seconds": job.timeout_seconds,
        }
        for job in sorted(jobs, key=lambda j: j.next_run)
    ]
```

**Response model:**

```python
class ScheduledJobResponse(BaseModel):
    job_id: int
    name: str
    owner: str                       # App unique_name that owns the job
    next_run: str                    # ISO datetime
    repeat: bool
    cancelled: bool
    trigger_type: str                # "IntervalTrigger", "CronTrigger", or "once"
    timeout_seconds: int
```

### 6.8 Job Execution Metrics (`src/hassette/core/scheduler_service.py`)

When the scheduler dispatches a job, there is no record of whether it succeeded, failed, or how long it took. We add a lightweight execution log as a `deque` on `SchedulerService`.

**JobExecutionRecord dataclass** (lives in `src/hassette/scheduler/classes.py`):

```python
@dataclass
class JobExecutionRecord:
    job_id: int
    job_name: str
    owner: str
    started_at: float                # Unix timestamp
    duration_ms: float               # Execution duration in milliseconds
    status: str                      # "success", "error", "cancelled"
    error_message: str | None = None
    error_type: str | None = None
```

**Changes to `SchedulerService`:**

The existing `run_job()` method gets a `try/finally` wrapper to record execution metrics. The actual job execution logic is unchanged.

```python
class SchedulerService(Service):
    _execution_log: deque[JobExecutionRecord]   # bounded ring buffer

    @classmethod
    def create(cls, hassette):
        ...
        inst._execution_log = deque(maxlen=hassette.config.web_api_job_history_size)
        ...

    async def run_job(self, job: ScheduledJob):
        """Run a scheduled job, recording execution metrics."""
        if job.cancelled:
            ...
            return

        started_at = time.monotonic()
        timestamp = time.time()
        status = "success"
        error_message = None
        error_type = None

        try:
            async_func = self.task_bucket.make_async_adapter(job.job)
            await async_func(*job.args, **job.kwargs)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception as exc:
            status = "error"
            error_message = str(exc)
            error_type = type(exc).__name__
            self.logger.exception("Error running job %s", job)
        finally:
            duration_ms = (time.monotonic() - started_at) * 1000
            record = JobExecutionRecord(
                job_id=job.job_id,
                job_name=job.name,
                owner=job.owner,
                started_at=timestamp,
                duration_ms=duration_ms,
                status=status,
                error_message=error_message,
                error_type=error_type,
            )
            self._execution_log.append(record)

    def get_execution_history(self, limit: int = 50, owner: str | None = None) -> list[JobExecutionRecord]:
        """Return recent job execution records, optionally filtered by owner."""
        entries = list(self._execution_log)
        if owner:
            entries = [e for e in entries if e.owner == owner]
        return entries[-limit:]
```

**DataSyncService integration:**

```python
def get_job_execution_history(self, limit: int = 50, owner: str | None = None) -> list[dict]:
    """Return recent job execution records, optionally filtered by owner."""
    records = self.hassette._scheduler_service.get_execution_history(limit, owner)
    return [asdict(r) for r in records]
```

**Response model:**

```python
class JobExecutionResponse(BaseModel):
    job_id: int
    job_name: str
    owner: str
    started_at: float
    duration_ms: float
    status: str                      # "success" | "error" | "cancelled"
    error_message: str | None = None
    error_type: str | None = None
```

---

## 7. REST API Endpoints

### `GET /api/health`

Returns `SystemStatusResponse`. Checks WebSocket connectivity, entity count from StateProxy, app count from AppHandler registry, and lists running core services.

### `GET /healthz`

Backwards-compatible health endpoint matching the old HealthService contract. Returns `{"status": "ok", "ws": "connected"}` (200) or `{"status": "degraded", "ws": "disconnected"}` (503). This ensures existing Docker `HEALTHCHECK` configurations continue to work without modification.

### `GET /api/entities`

Returns `EntityListResponse` (all entities). Reads from DataSyncService which delegates to StateProxy (in-memory cache). No HA API calls -- fast and adds no load to HA.

### `GET /api/entities/{entity_id}`

Returns `EntityStateResponse` (single entity) or 404.

### `GET /api/entities/domain/{domain}`

Returns `EntityListResponse` (entities in a domain).

### `GET /api/apps`

Returns `AppStatusResponse` with all app instances and their statuses.

### `GET /api/apps/{app_key}`

Returns `AppInstanceResponse` for first instance of the specified app key, or 404.

### `POST /api/apps/{app_key}/start`

Delegates to `AppHandler.start_app()`. Returns 202 Accepted immediately; the actual lifecycle change is broadcast over WebSocket. Gated behind `dev_mode` or `allow_reload_in_prod`.

### `POST /api/apps/{app_key}/stop`

Delegates to `AppHandler.stop_app()`. Same pattern as start.

### `POST /api/apps/{app_key}/reload`

Delegates to `AppHandler.reload_app()`. Same pattern as start.

### `GET /api/services`

Returns HA services list. Delegates to `hassette.api.get_services()`.

### `GET /api/events/recent?limit=50`

Returns recent events from DataSyncService event buffer.

### `GET /api/config`

Returns sanitized hassette configuration (token redacted).

### `GET /api/logs?limit=100&app_key=my_app&level=ERROR`

Returns recent log entries from the `LogCaptureHandler` ring buffer. All query parameters are optional:
- `limit` (default 100) -- max entries to return
- `app_key` -- filter to logs from a specific app (matches against `logger_name`)
- `level` -- minimum log level filter (e.g. `WARNING` returns WARNING, ERROR, CRITICAL)

Returns `list[LogEntryResponse]`.

### `GET /api/scheduler/jobs`

Returns all currently scheduled jobs across all apps, sorted by `next_run`. Returns `list[ScheduledJobResponse]`.

### `GET /api/scheduler/jobs?owner={app_unique_name}`

Same as above but filtered to a single app's jobs.

### `GET /api/scheduler/history?limit=50&owner={app_unique_name}`

Returns recent job execution records from the `SchedulerService` execution log. Both query parameters are optional. Returns `list[JobExecutionResponse]`.

---

## 8. WebSocket Endpoint

### `WS /api/ws`

Protocol:

1. Client connects.
2. Server sends `{"type": "connected", "data": {"entity_count": N, "app_count": M}}`.
3. Server pushes real-time messages:
   - `{"type": "state_changed", "data": {"entity_id": "...", "new_state": {...}, "old_state": {...}}}`
   - `{"type": "app_status_changed", "data": {"app_key": "...", "status": "..."}}`
   - `{"type": "service_status", "data": {"resource_name": "...", "status": "..."}}`
   - `{"type": "connectivity", "data": {"connected": true/false}}`
   - `{"type": "log", "data": {"timestamp": ..., "level": "...", "logger_name": "...", "message": "..."}}`
   - `{"type": "job_executed", "data": {"job_id": ..., "job_name": "...", "owner": "...", "status": "...", "duration_ms": ...}}`
4. Client can send `{"type": "ping"}` and server replies `{"type": "pong"}`.
5. Client can send `{"type": "subscribe", "data": {"logs": true, "min_log_level": "INFO"}}` to opt into log streaming (logs are not sent by default to avoid overwhelming the connection).
6. On disconnect, the server unregisters the client queue.

Implementation:

```python
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    data_sync = websocket.app.state.hassette._data_sync_service
    queue = await data_sync.register_ws_client()
    try:
        await websocket.send_json({"type": "connected", "data": {...}})
        async with anyio.create_task_group() as tg:
            tg.start_soon(_read_client, websocket)
            tg.start_soon(_send_from_queue, websocket, queue)
    except WebSocketDisconnect:
        pass
    finally:
        data_sync.unregister_ws_client(queue)
```

---

## 9. Implementation Order

Each step's dependencies are already complete by the time it is reached.

### Phase 1: Foundation

1. Add `fastapi` and `uvicorn` to `pyproject.toml` dependencies. Run `uv sync`.
2. Remove HealthService:
   - Delete `src/hassette/core/health_service.py`.
   - Remove `_health_service` from `Hassette.__init__()` in `src/hassette/core/core.py`.
   - Replace config fields: remove `run_health_service`, `health_service_port`, `health_service_log_level`; add all `web_api_*` fields.
   - Update tests that reference HealthService (`tests/integration/test_core.py`, `tests/conftest.py`).
3. Create the `src/hassette/web/` package skeleton: `__init__.py`, `models.py`, `dependencies.py`, `app.py`, `routes/__init__.py`.
4. Create response models in `src/hassette/web/models.py` (pure pydantic, no runtime deps).

### Phase 2: Core Infrastructure Changes

5. Add `LogCaptureHandler` and `LogEntry` to `src/hassette/logging_.py`. Install the handler in `enable_logging()`.
6. Add `JobExecutionRecord` to `src/hassette/scheduler/classes.py`.
7. Add `_execution_log` to `SchedulerService.create()`, wrap `run_job()` with metrics capture, add `get_execution_history()`.
8. Add `get_all()` to `_ScheduledJobQueue`, add `get_all_jobs()` to `SchedulerService`.

### Phase 3: DataSyncService

9. Create `src/hassette/core/data_sync_service.py` with event buffer, WS client registry, bus subscriptions, log handler wiring, and query methods (entity state, app status, events, logs, scheduled jobs, job history).
10. Register DataSyncService in `Hassette.__init__()` in `src/hassette/core/core.py`.
11. Write unit tests for DataSyncService.

### Phase 4: REST API Routes

12. Implement route modules one at a time: health (including `/healthz` backwards compat), entities, apps, services, events, logs, scheduler, config.
13. Implement `src/hassette/web/app.py` (the `create_fastapi_app()` factory).
14. Implement `src/hassette/web/dependencies.py`.

### Phase 5: WebApiService

15. Create `src/hassette/core/web_api_service.py` with `serve()` using uvicorn programmatic API.
16. Register WebApiService in `Hassette.__init__()`, replacing where `_health_service` was.

### Phase 6: WebSocket Endpoint

17. Implement `routes/ws.py` with dual-task loop for reading client messages and writing from broadcast queue. Include log subscription opt-in and job execution push.

### Phase 7: Testing and Polish

18. Write integration tests using `httpx.AsyncClient` with `ASGITransport`.
19. Update documentation.

---

## 10. Error Handling and Graceful Shutdown

### Error Handling

- **FastAPI exception handlers**: Register a global handler that catches `ResourceNotReadyError` and returns 503 Service Unavailable.
- **WebSocket errors**: Wrap the dual-loop in try/except catching `WebSocketDisconnect` and `asyncio.CancelledError`, unregistering the client cleanly.
- **StateProxy not ready**: Entity endpoints catch readiness errors and return 503.
- **App management errors**: Start/stop/reload endpoints catch exceptions from AppHandler and return 500 with the error message.

### Graceful Shutdown

Children are shut down in reverse order (per `core.py`). Since `WebApiService` and `DataSyncService` are added last, they are shut down first:

1. `WebApiService.on_shutdown()` -- cancels uvicorn, draining active connections and closing WebSocket connections.
2. `DataSyncService.on_shutdown()` -- removes bus listeners, closes all WS client queues, clears the event buffer.

This ordering ensures the web UI sees a clean disconnect before internal services stop.

### Conditional Startup

When `run_web_api` is `False`, both services immediately mark themselves ready and return, adding zero overhead. This mirrors the pattern the old `HealthService.serve()` used.

---

## 11. Security Considerations

- **No authentication in Phase 1**: The web API is initially for local/development use. A future phase should add token-based authentication.
- **CORS**: Configurable origins via `web_api_cors_origins`, defaulting to common local dev ports.
- **Config endpoint**: Must redact `token` before returning config data. Use `hassette.config.model_dump(exclude={"token"})`.
- **App management**: Start/stop/reload endpoints are gated behind `dev_mode or allow_reload_in_prod`, matching existing AppHandler guards.

---

## 12. Potential Challenges and Mitigations

| Challenge | Mitigation |
|---|---|
| uvicorn event loop conflicting with hassette's | Use `uvicorn.Config(lifespan="off")` and run `Server.serve()` directly in the existing event loop, not `uvicorn.run()` which creates its own loop. |
| High-frequency state_changed events overwhelming WS clients | Bounded broadcast queue per client; overflow drops messages for slow clients. Event buffer has configurable max size (deque maxlen). |
| Thread safety of StateProxy reads from FastAPI handlers | StateProxy uses CPython-atomic dict reads. FastAPI handlers run in the same asyncio loop, so no thread-safety issue. |
| Startup ordering / deadlocks | DataSyncService and WebApiService use `wait_for_ready()` with the configured `startup_timeout_seconds`, matching StateProxy and AppHandler patterns. |
| Testing FastAPI routes without a running HA instance | Use `httpx.AsyncClient` with `ASGITransport` pointed at the FastAPI app, with mocked DataSyncService returning fixture data. |
| Type checking with Pyright | All new code has full type annotations. Use `if TYPE_CHECKING:` imports for hassette types to avoid circular imports, matching the codebase pattern. |

---

## 13. Files Summary

### New files:

| File | Purpose |
|---|---|
| `src/hassette/core/data_sync_service.py` | DataSyncService Resource |
| `src/hassette/core/web_api_service.py` | WebApiService (uvicorn runner) |
| `src/hassette/web/__init__.py` | Package init |
| `src/hassette/web/app.py` | FastAPI app factory |
| `src/hassette/web/dependencies.py` | FastAPI Depends() helpers |
| `src/hassette/web/models.py` | Pydantic response models |
| `src/hassette/web/routes/__init__.py` | Routes package init |
| `src/hassette/web/routes/health.py` | Health/status endpoint |
| `src/hassette/web/routes/entities.py` | Entity state endpoints |
| `src/hassette/web/routes/apps.py` | App management endpoints |
| `src/hassette/web/routes/services.py` | HA services endpoint |
| `src/hassette/web/routes/events.py` | Event history endpoint |
| `src/hassette/web/routes/logs.py` | Log query endpoint |
| `src/hassette/web/routes/scheduler.py` | Scheduled jobs and execution history endpoints |
| `src/hassette/web/routes/config.py` | Config endpoint |
| `src/hassette/web/routes/ws.py` | WebSocket endpoint |
| `tests/unit/core/test_data_sync_service.py` | DataSyncService unit tests |
| `tests/integration/test_web_api.py` | WebApiService integration tests |

### Files to delete:

| File | Reason |
|---|---|
| `src/hassette/core/health_service.py` | Replaced by WebApiService with FastAPI |

### Existing files to modify:

| File | Change |
|---|---|
| `pyproject.toml` | Add `fastapi` and `uvicorn` dependencies |
| `src/hassette/config/config.py` | Remove `run_health_service`, `health_service_port`, `health_service_log_level`; add all `web_api_*` fields |
| `src/hassette/core/core.py` | Remove `HealthService` import and `_health_service` child; add `DataSyncService` and `WebApiService` as children |
| `src/hassette/core/__init__.py` | Export new service classes, remove `HealthService` export (if applicable) |
| `src/hassette/logging_.py` | Add `LogCaptureHandler` and `LogEntry` classes; install handler in `enable_logging()` |
| `src/hassette/scheduler/classes.py` | Add `JobExecutionRecord` dataclass |
| `src/hassette/core/scheduler_service.py` | Add `_execution_log` deque, wrap `run_job()` with metrics, add `get_execution_history()`, add `get_all_jobs()` and `get_all()` on `_ScheduledJobQueue` |
| `tests/integration/test_core.py` | Replace `HealthService` assertions with `WebApiService` assertions |
| `tests/conftest.py` | Replace `run_health_service=False` / `health_service_port` with `run_web_api=False` / `web_api_port` in test configs |
| `src/hassette/config/hassette.dev.toml` | Replace `run_health_service`, `health_service_port`, `health_service_log_level` with `web_api_*` equivalents |
| `src/hassette/config/hassette.prod.toml` | Replace `run_health_service`, `health_service_port`, `health_service_log_level` with `web_api_*` equivalents |

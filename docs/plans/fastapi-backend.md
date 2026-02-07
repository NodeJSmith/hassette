# Implementation Plan: FastAPI Backend and Data Sync Service

## 1. Summary

Add a FastAPI-based HTTP/WebSocket backend and a DataSyncService to hassette. These new services expose REST endpoints and a real-time WebSocket channel that a future web UI can consume. The design follows hassette's existing patterns: the Resource/Service hierarchy for lifecycle management, the Bus for event subscriptions, StateProxy for cached entity state, and pydantic-settings for configuration.

---

## 2. Architectural Decisions

### 2.1 FastAPI vs. Extending aiohttp

**Decision: Introduce FastAPI as a new service; keep the existing HealthService on aiohttp unchanged.**

Rationale:

- The existing `HealthService` is deliberately minimal (a single `/healthz` endpoint) and runs on aiohttp, which is also a hard dependency for the WebSocket client (`WebsocketService`). Replacing it risks breaking the existing health-check contract for Docker deployments.
- FastAPI provides automatic OpenAPI docs, pydantic model serialization (matching hassette's pydantic-first philosophy), native WebSocket support, and dependency injection -- all superior for a rich API surface.
- FastAPI's ASGI underpinning (uvicorn) runs cleanly in an asyncio event loop alongside the existing aiohttp client sessions. The two servers bind to different ports and do not conflict.
- In the future, the `/healthz` endpoint could optionally be mounted as a FastAPI sub-route, but that is explicitly out of scope for this phase.

### 2.2 Where New Services Live in the Resource Hierarchy

The new services are children of `Hassette` (the root Resource), just like `BusService`, `WebsocketService`, `HealthService`, and `AppHandler`.

```
Hassette (root Resource)
  +-- BusService
  +-- WebsocketService
  +-- HealthService        (unchanged, aiohttp)
  +-- AppHandler
  +-- StateProxy
  +-- ...existing services...
  +-- DataSyncService      (NEW -- Resource)
  +-- WebApiService        (NEW -- Service, runs uvicorn)
```

`DataSyncService` is a plain `Resource` (not `Service`) because it does not have a long-running `serve()` loop; it passively subscribes to Bus events and exposes query methods. `WebApiService` is a `Service` because it runs uvicorn in `serve()` until cancelled.

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

## 4. Configuration Additions

New fields in `HassetteConfig` (`src/hassette/config/config.py`):

```python
# Web API configuration
run_web_api: bool = Field(default=False)
"""Whether to run the web API service for the UI backend."""

web_api_host: str = Field(default="0.0.0.0")
"""Host to bind the web API server to."""

web_api_port: int = Field(default=8127)
"""Port to run the web API server on."""

web_api_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
"""Logging level for the web API service."""

web_api_cors_origins: tuple[str, ...] = Field(
    default=("http://localhost:3000", "http://localhost:5173")
)
"""Allowed CORS origins for the web API, typically the UI dev server."""

web_api_event_buffer_size: int = Field(default=500)
"""Maximum number of recent events to keep in the DataSyncService ring buffer."""
```

TOML example (`hassette.toml`):

```toml
[hassette]
run_web_api = true
web_api_port = 8127
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
      health.py                # GET /api/health
      entities.py              # GET /api/entities, /api/entities/{id}, /api/entities/domain/{domain}
      apps.py                  # GET/POST /api/apps, /api/apps/{key}, /api/apps/{key}/start|stop|reload
      services.py              # GET /api/services
      events.py                # GET /api/events/recent
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

---

## 7. REST API Endpoints

### `GET /api/health`

Returns `SystemStatusResponse`. Checks WebSocket connectivity, entity count from StateProxy, app count from AppHandler registry, and lists running core services.

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
4. Client can send `{"type": "ping"}` and server replies `{"type": "pong"}`.
5. On disconnect, the server unregisters the client queue.

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

### Phase 1: Foundation (no behavioral changes)

1. Add `fastapi` and `uvicorn` to `pyproject.toml` dependencies. Run `uv sync`.
2. Add configuration fields to `HassetteConfig` in `src/hassette/config/config.py`. All default to disabled (`run_web_api=False`).
3. Create the `src/hassette/web/` package skeleton: `__init__.py`, `models.py`, `dependencies.py`, `app.py`, `routes/__init__.py`.
4. Create response models in `src/hassette/web/models.py` (pure pydantic, no runtime deps).

### Phase 2: DataSyncService

5. Create `src/hassette/core/data_sync_service.py` with event buffer, WS client registry, bus subscriptions, query methods, and broadcast.
6. Register DataSyncService in `Hassette.__init__()` in `src/hassette/core/core.py`.
7. Write unit tests for DataSyncService.

### Phase 3: REST API Routes

8. Implement route modules one at a time: health, entities, apps, services, events, config.
9. Implement `src/hassette/web/app.py` (the `create_fastapi_app()` factory).
10. Implement `src/hassette/web/dependencies.py`.

### Phase 4: WebApiService

11. Create `src/hassette/core/web_api_service.py` with `serve()` using uvicorn programmatic API.
12. Register WebApiService in `Hassette.__init__()`.

### Phase 5: WebSocket Endpoint

13. Implement `routes/ws.py` with dual-task loop for reading client messages and writing from broadcast queue.

### Phase 6: Testing and Polish

14. Write integration tests using `httpx.AsyncClient` with `ASGITransport`.
15. Update documentation.

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

When `run_web_api` is `False` (the default), both services immediately mark themselves ready and return, adding zero overhead. This mirrors the pattern in `HealthService.serve()`.

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
| `src/hassette/web/routes/config.py` | Config endpoint |
| `src/hassette/web/routes/ws.py` | WebSocket endpoint |
| `tests/unit/core/test_data_sync_service.py` | DataSyncService unit tests |
| `tests/integration/test_web_api.py` | WebApiService integration tests |

### Existing files to modify:

| File | Change |
|---|---|
| `pyproject.toml` | Add `fastapi` and `uvicorn` dependencies |
| `src/hassette/config/config.py` | Add web API config fields |
| `src/hassette/core/core.py` | Register DataSyncService and WebApiService as children |
| `src/hassette/core/__init__.py` | Export new service classes (if applicable) |

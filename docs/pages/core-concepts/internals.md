---
hide:
  - toc
---

# Hassette Architecture Overview

Hassette is an async-first Python framework for building Home Assistant automations. It connects to Home Assistant over WebSocket, routes incoming events through a typed pub/sub bus, dispatches them to user-defined App classes, and provides a web UI for monitoring the running system.

---

## 1. Component Ownership

Every component is a `Resource` in a parent/child tree rooted at the `Hassette` instance. Apps get four lightweight handles (`Bus`, `Scheduler`, `Api`, `StateManager`) that delegate to shared framework services.

```mermaid
graph TD
    accTitle: Component Ownership Tree
    accDescr: Parent-child resource hierarchy from Hassette root to per-app handles

    Hassette

    subgraph infra["Infrastructure Services"]
        EventStreamService
        DatabaseService
        CommandExecutor
        WebsocketService
    end

    subgraph core["Core Services"]
        BusService
        SchedulerService
        ApiResource
        StateProxy
    end

    subgraph web["Web Layer"]
        WebApiService
        RuntimeQueryService
        TelemetryQueryService
    end

    subgraph apps["App Management"]
        AppHandler
        AppLifecycleService
        AppRegistry
    end

    Hassette --- infra
    Hassette --- core
    Hassette --- web
    Hassette --- apps

    AppHandler --> AppLifecycleService
    AppHandler --> AppRegistry

    subgraph perapp["Per-App Resources (0..N instances)"]
        App
        App --> Bus
        App --> Scheduler
        App --> Api
        App --> StateManager
    end

    AppLifecycleService --> App

    style infra fill:#f0f0f0,stroke:#999
    style core fill:#e8f0ff,stroke:#6688cc
    style web fill:#f0f8e8,stroke:#88aa66
    style apps fill:#fff0e8,stroke:#cc8844
    style perapp fill:#f8f0ff,stroke:#8866cc
```

Per-app handles are thin wrappers. When an app shuts down, its `Bus` removes its listeners from `BusService`, its `Scheduler` removes its jobs from `SchedulerService`, and so on. The shared services continue running for other apps.

---

## 2. Service Dependencies

Services declare `depends_on` at the class level. The framework computes wave-based startup order from these declarations. An arrow from A to B means "A waits for B to be ready."

```mermaid
graph TD
    accTitle: Service Dependency Graph
    accDescr: Which services must be ready before others can initialize

    DB[DatabaseService]
    WS[WebsocketService]
    CMD[CommandExecutor]
    API[ApiResource]
    BUS[BusService]
    SCHED[SchedulerService]
    SP[StateProxy]
    AH[AppHandler]
    RQS[RuntimeQueryService]
    TQS[TelemetryQueryService]
    WEB[WebApiService]

    CMD --> DB
    TQS --> DB
    API --> WS
    SP --> WS & API & BUS & SCHED
    AH --> WS & API & BUS & SCHED & SP
    RQS --> BUS & SP & AH
    WEB --> RQS & TQS

    style DB fill:#f0f0f0,stroke:#999
    style WS fill:#f0f0f0,stroke:#999
    style BUS fill:#e8f0ff,stroke:#6688cc
    style SCHED fill:#e8f0ff,stroke:#6688cc
    style SP fill:#e8f0ff,stroke:#6688cc
    style API fill:#e8f0ff,stroke:#6688cc
    style AH fill:#fff0e8,stroke:#cc8844
    style WEB fill:#f0f8e8,stroke:#88aa66
    style RQS fill:#f0f8e8,stroke:#88aa66
    style TQS fill:#f0f8e8,stroke:#88aa66
    style CMD fill:#f0f0f0,stroke:#999
```

`DatabaseService`, `WebsocketService`, `BusService`, and `SchedulerService` have no dependencies and start in wave 0. `WebApiService` is the deepest node (via `RuntimeQueryService` and `AppHandler`).

---

## 3. Event and Data Flow

Events flow from Home Assistant through a four-stage inbound pipeline. Outbound calls go through the `Api` handle back to HA via REST or WebSocket.

```mermaid
flowchart LR
    accTitle: Event and Data Flow
    accDescr: Inbound event pipeline and outbound API calls

    HA["Home Assistant"]

    subgraph inbound["Inbound Pipeline"]
        direction LR
        WS["WebsocketService"]
        ESS["EventStreamService"]
        BS["BusService"]
        CE["CommandExecutor"]
    end

    subgraph app["App Handler"]
        Handler["on_* handler"]
    end

    subgraph outbound["Outbound"]
        AR["ApiResource<br/>(REST)"]
        WSOut["WebsocketService<br/>(WS send)"]
    end

    HA -- "WS frame" --> WS
    WS -- "memory channel" --> ESS
    ESS --> BS
    BS -- "predicate filter" --> CE
    CE -- "invoke" --> Handler
    Handler -- "api.call_service()" --> AR & WSOut
    AR -- "HTTP" --> HA
    WSOut -- "WS frame" --> HA

    WS -. "state_changed<br/>(priority 100)" .-> SP["StateProxy"]
    SP -. "self.states.*" .-> Handler
```

`StateProxy` subscribes to state_changed events at priority 100, so its cache is always updated before any user handler sees the event. The `CommandExecutor` records every invocation to SQLite for the telemetry UI.

| Failure | Behavior |
|---|---|
| WS disconnect | Exponential backoff retry (max 5 attempts) |
| Auth failure | Process exits, no retry |
| Handler timeout | Logged, invocation recorded as timed-out |
| DB write failure | 3 retries, then dropped with counter increment |

---

## 4. App Lifecycle

The framework manages all state transitions. User code implements `on_initialize` (register listeners and jobs) and `on_shutdown` (release resources). The other hooks (`before_*`, `after_*`) are available but rarely needed.

```mermaid
sequenceDiagram
    accTitle: App Lifecycle
    accDescr: From manifest loading through initialization to shutdown

    participant Handler as AppHandler
    participant App
    participant Bus as App.bus
    participant Sched as App.scheduler

    rect rgb(232, 240, 255)
        Note over Handler,App: Startup
        Handler->>App: instantiate(config)
        App->>Bus: add_child()
        App->>Sched: add_child()
    end

    rect rgb(240, 248, 232)
        Note over App,Sched: Initialize
        App->>App: on_initialize()
        Note right of App: Register listeners + schedule jobs
        Bus->>Bus: mark_ready()
        Sched->>Sched: mark_ready()
        App->>App: handle_running()
    end

    rect rgb(255, 240, 232)
        Note over App,Sched: Shutdown
        App->>App: on_shutdown()
        Bus->>Bus: remove all listeners
        Sched->>Sched: remove all jobs
        App->>App: handle_stop()
    end
```

- All framework services (`WebsocketService`, `BusService`, `SchedulerService`, `StateProxy`) are guaranteed ready before any app's `on_initialize` runs — enforced by `AppHandler.depends_on`.
- `handle_running()` emits `HASSETTE_EVENT_APP_STATE_CHANGED`, which other apps can subscribe to for sequenced startup.
- In dev mode, `FileWatcherService` triggers hot-reload of only the affected app keys.

---

## 5. Bus Internals

The `Bus` handle translates `on_*()` calls into `Listener` objects, which the shared `BusService` indexes by topic for fast dispatch.

```mermaid
flowchart LR
    accTitle: Bus Event Routing
    accDescr: From app subscription through predicate filtering to handler invocation

    subgraph registration["Registration"]
        on["Bus.on_*()"]
        pca["Predicates (P)<br/>Conditions (C)<br/>Accessors (A)"]
        L["Listener"]
        on --> pca --> L
    end

    subgraph routing["BusService Router"]
        exact["Exact topics<br/>light.kitchen"]
        glob["Glob topics<br/>light.*"]
    end

    subgraph dispatch["Dispatch"]
        match["Predicate check"]
        exec["CommandExecutor"]
        handler["App handler"]
    end

    L -- "add_listener()" --> exact & glob
    exact & glob -- "event arrives" --> match
    match -- "passed" --> exec --> handler

    style registration fill:#e8f0ff,stroke:#6688cc
    style routing fill:#f0f8e8,stroke:#88aa66
    style dispatch fill:#fff0e8,stroke:#cc8844
```

**Topic expansion.** A `state_changed` event for `light.office` produces three topics in specificity order: `hass.event.state_changed.light.office`, `hass.event.state_changed.light.*`, `hass.event.state_changed`.

**Listener behaviors:**

| Option | Effect |
|---|---|
| `debounce=N` | Buffer events, fire only if quiet for N seconds |
| `throttle=N` | Fire immediately, suppress for N seconds |
| `duration=N` | Fire only if predicate still matches after N seconds |
| `once=True` | Auto-remove after first invocation |
| `priority=N` | Lower values dispatch first (StateProxy uses 100) |

---

## 6. Scheduler Internals

The `Scheduler` handle wraps convenience methods around five trigger types. All jobs end up in a shared min-heap inside `SchedulerService`.

```mermaid
flowchart LR
    accTitle: Scheduler Job Pipeline
    accDescr: From convenience methods through triggers to the dispatch loop

    subgraph api["Scheduler API"]
        methods["run_in() / run_once()<br/>run_every() / run_daily()<br/>run_cron() / schedule()"]
    end

    subgraph triggers["Triggers"]
        After["After<br/><i>one-shot delay</i>"]
        Once["Once<br/><i>one-shot at time</i>"]
        Every["Every<br/><i>recurring interval</i>"]
        Daily["Daily<br/><i>DST-safe cron</i>"]
        Cron["Cron<br/><i>croniter expression</i>"]
    end

    subgraph engine["SchedulerService"]
        heap["Min-heap<br/>by next_run"]
        loop["serve() loop"]
        exec["CommandExecutor"]
    end

    methods --> triggers
    triggers -- "ScheduledJob" --> heap
    heap -- "pop due" --> loop
    loop --> exec
    exec -. "re-enqueue<br/>if recurring" .-> heap

    style api fill:#e8f0ff,stroke:#6688cc
    style triggers fill:#f0f8e8,stroke:#88aa66
    style engine fill:#fff0e8,stroke:#cc8844
```

- `Daily` uses cron internally for DST-safe wall-clock scheduling. A naive 24-hour interval would drift across DST transitions.
- `jitter` adds random offset at enqueue time to spread concurrent starts.
- Job groups (`group=`) enable bulk cancellation. Named jobs (`name=`) support deduplication via `if_exists="skip"`.

---

## 7. Api Internals

The per-app `Api` handle delegates all transport to shared singletons. Single-entity reads use REST; bulk reads and service calls use WebSocket.

```mermaid
flowchart LR
    accTitle: Api Transport
    accDescr: How per-app Api delegates to shared REST and WebSocket transports

    subgraph app["Per-App"]
        Api
    end

    subgraph transport["Shared Singletons"]
        AR["ApiResource<br/>(aiohttp)"]
        WS["WebsocketService"]
    end

    subgraph ha["Home Assistant"]
        REST["REST API"]
        WSAPI["WebSocket API"]
    end

    Api -- "get_state(id)" --> AR
    Api -- "call_service()<br/>get_states()" --> WS
    AR -- "HTTP" --> REST
    WS -- "WS frame" --> WSAPI

    style app fill:#e8f0ff,stroke:#6688cc
    style transport fill:#fff0e8,stroke:#cc8844
    style ha fill:#f0f0f0,stroke:#999
```

| Method | Transport | Pattern |
|---|---|---|
| `get_state(entity_id)` | REST | `GET /api/states/{id}` |
| `get_states()` | WebSocket | `get_states` command |
| `call_service()` | WebSocket | fire-and-forget or `send_and_wait` |
| `fire_event()` | WebSocket | fire-and-forget |

Auth: long-lived access token from `HassetteConfig.token`. Injected as `Bearer` header (REST) and `auth` handshake (WebSocket).

---

## 8. StateManager and StateProxy

`StateProxy` maintains an in-memory cache of all entity states. `StateManager` provides typed per-app access with Pydantic model validation and caching.

```mermaid
flowchart TD
    accTitle: State Management
    accDescr: How entity states flow from HA through the cache to typed app access

    subgraph sources["Cache Population"]
        bus_sub["Bus subscription<br/>(priority 100)"]
        poll["Periodic poll<br/>(run_every)"]
    end

    subgraph proxy["StateProxy"]
        cache["In-memory dict<br/>entity_id to HassStateDict"]
    end

    subgraph access["StateManager (per-app)"]
        attr["self.states.light<br/><i>DomainStates[LightState]</i>"]
        item["self.states[CustomState]<br/><i>DomainStates[T]</i>"]
        get["self.states.get(entity_id)<br/><i>raw lookup</i>"]
    end

    subgraph convert["Type Conversion"]
        SR["StateRegistry<br/>domain to model class"]
        TR["TypeRegistry<br/>scalar conversion"]
    end

    bus_sub --> cache
    poll --> cache
    cache --> attr & item & get
    attr & item --> SR & TR

    style sources fill:#f0f8e8,stroke:#88aa66
    style proxy fill:#fff0e8,stroke:#cc8844
    style access fill:#e8f0ff,stroke:#6688cc
    style convert fill:#f8f0ff,stroke:#8866cc
```

- Read access is lock-free — CPython dict assignment is atomic; the proxy replaces whole objects rather than mutating.
- `DomainStates` caches validated Pydantic models keyed by `context_id` (a UUID from HA). Same context ID = return cached model without re-validating.
- On disconnect, `StateProxy` clears the cache and marks itself not-ready. On reconnect, it bulk-reloads via `get_states_raw()`.

---

## 9. Web/UI Layer

The web layer is opt-in. `WebApiService` starts a uvicorn/FastAPI server. The frontend is a Preact SPA. Two data source services provide live and historical data.

```mermaid
flowchart LR
    accTitle: Web Layer
    accDescr: How the frontend connects to backend data sources

    subgraph browser["Browser"]
        SPA["Preact SPA"]
    end

    subgraph server["WebApiService"]
        rest["REST endpoints<br/>/api/health, /api/apps,<br/>/api/telemetry/*, ..."]
        ws["/api/ws<br/>WebSocket"]
        static["Static files<br/>SPA catch-all"]
    end

    subgraph data["Data Sources"]
        RQS["RuntimeQueryService<br/><i>live state, event buffer,<br/>WS broadcast</i>"]
        TQS["TelemetryQueryService<br/><i>SQLite: listeners, jobs,<br/>errors, sessions</i>"]
    end

    SPA -- "fetch" --> rest
    SPA <-- "push events" --> ws
    rest --> RQS & TQS
    ws --> RQS

    style browser fill:#e8f0ff,stroke:#6688cc
    style server fill:#fff0e8,stroke:#cc8844
    style data fill:#f0f8e8,stroke:#88aa66
```

- `RuntimeQueryService` subscribes to bus events and fan-out broadcasts to all connected WebSocket clients via `asyncio.Queue` per client.
- The SPA catch-all returns `index.html` for all non-asset paths, enabling client-side routing.
- When `config.run_web_api` is False, the service blocks on `shutdown_event.wait()` without binding a port, preserving the dependency graph.

---

## 10. Resource Lifecycle State Machine

Every component extends `Resource` (synchronous init) or `Service` (long-running `serve()` loop). The `LifecycleMixin` provides status transitions and readiness signaling.

```mermaid
stateDiagram-v2
    accTitle: Resource Lifecycle States
    accDescr: Status transitions for all framework components

    [*] --> NOT_STARTED
    NOT_STARTED --> STARTING : start()
    STARTING --> RUNNING : handle_running()
    RUNNING --> STOPPING : shutdown()
    STOPPING --> STOPPED : handle_stop()
    STARTING --> FAILED : error
    RUNNING --> FAILED : error
    RUNNING --> CRASHED : serve() exits (Service only)
    FAILED --> STARTING : restart()
    STOPPED --> [*]
```

**Readiness vs. running.** These are separate concerns:

- `handle_running()` sets status to RUNNING and emits an event — other components can observe lifecycle state
- `mark_ready()` sets the `ready_event` that unblocks `depends_on` waiters — a Resource calls this at the end of `on_initialize()`; a Service calls it inside `serve()` once actually processing

**Wave startup.** Dependencies are computed into topological levels. Each wave starts concurrently via `gather()`, but waves run sequentially — all dependencies are guaranteed ready before dependents begin. Shutdown proceeds in reverse wave order. A per-wave timeout triggers `_force_terminal()` on non-compliant children.

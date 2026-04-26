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
        App --> Cache
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

Services declare `depends_on` at the class level. The framework computes wave-based startup order from these declarations. Arrows point from dependents down to their dependencies — services at the top start last.

```mermaid
graph BT
    accTitle: Service Dependency Graph
    accDescr: Wave-based startup order, wave 0 at the top

    subgraph wave0["Wave 0 — No Dependencies"]
        DB[DatabaseService]
        WS[WebsocketService]
        BUS[BusService]
        SCHED[SchedulerService]
    end

    subgraph wave1["Wave 1"]
        CMD[CommandExecutor]
        API[ApiResource]
    end

    subgraph wave2["Wave 2"]
        SP[StateProxy]
        TQS[TelemetryQueryService]
    end

    subgraph wave3["Wave 3"]
        AH[AppHandler]
    end

    subgraph wave4["Wave 4"]
        RQS[RuntimeQueryService]
    end

    subgraph wave5["Wave 5 — Last to Start"]
        WEB[WebApiService]
    end

    CMD --> DB
    TQS --> DB
    API --> WS
    SP --> WS & API & BUS & SCHED
    AH --> WS & API & BUS & SCHED & SP
    RQS --> BUS & SP & AH
    WEB --> RQS & TQS

    style wave0 fill:#e8f0ff,stroke:#6688cc
    style wave1 fill:#dde8f8,stroke:#6688cc
    style wave2 fill:#d0e0f0,stroke:#6688cc
    style wave3 fill:#c4d8e8,stroke:#6688cc
    style wave4 fill:#b8d0e0,stroke:#6688cc
    style wave5 fill:#acc8d8,stroke:#6688cc
```

Shutdown proceeds in reverse wave order — `WebApiService` stops first, `DatabaseService` and `WebsocketService` stop last.

---

## 3. Event and Data Flow

Events flow from Home Assistant through a four-stage inbound pipeline. Outbound calls go through the `Api` handle back to HA via REST or WebSocket.

```mermaid
flowchart TD
    accTitle: Event and Data Flow
    accDescr: Inbound event pipeline and outbound API calls

    subgraph ha_in["Home Assistant"]
        HA_IN(("Inbound<br/>WS events"))
    end

    subgraph inbound["Inbound Pipeline"]
        WS["WebsocketService<br/><i>receive loop</i>"]
        ESS["EventStreamService<br/><i>memory channel</i>"]
        BS["BusService<br/><i>topic expand + filter</i>"]
        CE["CommandExecutor<br/><i>invoke + record</i>"]
        WS --> ESS --> BS --> CE
    end

    subgraph cache["State Cache"]
        SP["StateProxy"]
    end

    subgraph app["App"]
        Handler["on_* handler"]
    end

    subgraph outbound["Outbound"]
        AR["ApiResource<br/>(REST)"]
        WSOut["WebsocketService<br/>(WS send)"]
    end

    subgraph ha_out["Home Assistant"]
        HA_OUT(("Outbound<br/>WS / REST"))
    end

    HA_IN --> WS
    WS -. "state_changed<br/>(priority 100)" .-> SP
    CE --> Handler
    SP -. "self.states.*" .-> Handler
    Handler --> AR & WSOut
    AR & WSOut --> HA_OUT

    style ha_in fill:#f0f0f0,stroke:#999
    style ha_out fill:#f0f0f0,stroke:#999
    style inbound fill:#e8f0ff,stroke:#6688cc
    style cache fill:#f0f8e8,stroke:#88aa66
    style app fill:#fff0e8,stroke:#cc8844
    style outbound fill:#f8f0ff,stroke:#8866cc
```

`StateProxy` subscribes to state_changed events at priority 100, so its cache is always updated before any user handler sees the event. The `CommandExecutor` records every invocation to SQLite for the telemetry UI.

| Failure | Behavior |
|---|---|
| WS disconnect | Exponential backoff retry (max 5 attempts) |
| Auth failure | Process exits, no retry |
| Handler timeout | Logged, invocation recorded as timed-out |
| DB write failure | 3 retries, then dropped with counter increment |

---

## 4. Bus Internals

The `Bus` handle translates `on_*()` calls into `Listener` objects, which the shared `BusService` indexes by topic for fast dispatch.

```mermaid
flowchart TD
    accTitle: Bus Event Routing
    accDescr: From app subscription through predicate filtering to handler invocation

    subgraph registration["Registration"]
        on["Bus.on_*()"]
        pca["Predicates (P)<br/>Conditions (C)<br/>Accessors (A)"]
        L["Listener"]
        on --> pca --> L
    end

    subgraph routing["BusService Router"]
        exact["Exact topics<br/><i>light.kitchen</i>"]
        glob["Glob topics<br/><i>light.*</i>"]
    end

    subgraph dispatch["Dispatch"]
        match["Predicate check"]
        exec["CommandExecutor"]
        handler["App handler"]
        match --> exec --> handler
    end

    L -- "add_listener()" --> exact & glob
    exact & glob -- "event arrives" --> match

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

## 5. Scheduler Internals

The `Scheduler` handle wraps convenience methods (`run_in`, `run_once`, `run_every`, `run_daily`, `run_cron`, `schedule`) around trigger objects. All jobs end up in a shared min-heap inside `SchedulerService`.

```mermaid
flowchart TD
    accTitle: Scheduler Job Pipeline
    accDescr: From convenience methods through triggers to the dispatch loop

    subgraph api["Scheduler API"]
        methods["run_*() / schedule()"]
    end

    subgraph triggers["Triggers"]
        T["Trigger<br/><i>implements TriggerProtocol</i>"]
    end

    subgraph engine["SchedulerService"]
        heap["Min-heap<br/>by next_run"]
        loop["serve() loop"]
        exec["CommandExecutor"]
        heap -- "pop due" --> loop --> exec
    end

    methods --> T
    T -- "ScheduledJob" --> heap
    exec -. "re-enqueue<br/>if recurring" .-> heap

    style api fill:#e8f0ff,stroke:#6688cc
    style triggers fill:#f0f8e8,stroke:#88aa66
    style engine fill:#fff0e8,stroke:#cc8844
```

Built-in triggers: `After` (one-shot delay), `Once` (one-shot at time), `Every` (recurring interval), `Daily` (DST-safe cron), `Cron` (croniter expression). Custom triggers implement `TriggerProtocol`.

- `Daily` uses cron internally for DST-safe wall-clock scheduling. A naive 24-hour interval would drift across DST transitions.
- `jitter` adds random offset at enqueue time to spread concurrent starts.
- Job groups (`group=`) enable bulk cancellation. Named jobs (`name=`) support deduplication via `if_exists="skip"`.

---

## 6. Api Internals

The per-app `Api` handle delegates all transport to shared singletons. Single-entity reads use REST; bulk reads and service calls use WebSocket.

```mermaid
flowchart TD
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

## 7. StateManager and StateProxy

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

## 8. Web/UI Layer

The web layer is opt-in. `WebApiService` starts a uvicorn/FastAPI server. The frontend is a Preact SPA. Two data source services provide live and historical data.

```mermaid
flowchart TD
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

## 9. Resource Lifecycle

Every component extends `Resource` (synchronous init) or `Service` (long-running `serve()` loop). The `LifecycleMixin` provides status transitions and readiness signaling.

### State Transitions

```mermaid
flowchart TD
    accTitle: Resource Lifecycle States
    accDescr: Status transitions for all framework components

    NOT_STARTED:::neutral -- "start()" --> STARTING:::active
    STARTING -- "handle_running()" --> RUNNING:::active
    RUNNING -- "shutdown()" --> STOPPING:::active
    STOPPING -- "handle_stop()" --> STOPPED:::neutral

    STARTING -- "error" --> FAILED:::error
    RUNNING -- "error" --> FAILED
    RUNNING -- "serve() exits" --> CRASHED:::error
    FAILED -- "restart()" --> STARTING

    classDef neutral fill:#f0f0f0,stroke:#999,color:#333
    classDef active fill:#e8f0ff,stroke:#6688cc,color:#333
    classDef error fill:#ffe8e8,stroke:#cc6666,color:#333
```

### Readiness vs. Running

These are **separate concerns** that are easy to confuse:

| Concept | Method | What it does | Who calls it |
|---|---|---|---|
| **Status** | `handle_running()` | Sets RUNNING, emits event | Framework (automatic) |
| **Readiness** | `mark_ready()` | Unblocks `depends_on` waiters | Resource: end of `on_initialize()`. Service: inside `serve()` once processing |

A component can be RUNNING but not ready (still initializing internal state), or ready but not yet RUNNING (edge case during transition).

### Wave Startup and Shutdown

Dependencies are computed into topological levels. Each wave starts concurrently via `gather()`, but waves run sequentially — all dependencies are guaranteed ready before dependents begin.

Shutdown proceeds in reverse wave order. A per-wave timeout triggers `_force_terminal()` on non-compliant children, which recursively force-stops without running hooks (accepted risk for stuck services).

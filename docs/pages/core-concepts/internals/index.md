# Architecture & Data Flow

This section covers Hassette's internal architecture for contributors and advanced users. App authors do not need this section to build automations.

Three pages make up the internals section:

- **Architecture & Data Flow** (this page): event pipeline, service dependencies, component ownership
- [Lifecycle & Supervision](lifecycle.md): state machines, readiness signaling, `ServiceWatcher` restart logic
- [Per-Service Internals](service-details.md): bus routing, scheduler dispatch, database schema, state cache, web layer

## Event Pipeline

An event travels through four stages before reaching a handler.

`WebsocketService` receives raw frames from Home Assistant over a persistent WebSocket connection. It forwards each event to `EventStreamService`, which owns an anyio memory channel that decouples reception from processing. `BusService` reads from that channel and expands each event into a set of topics ordered by specificity. It then filters the topics against registered listeners. `CommandExecutor` invokes the matching handler and writes an execution record to SQLite.

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
    style inbound fill:#fff0e8,stroke:#cc8844
    style cache fill:#f0f8e8,stroke:#88aa66
    style app fill:#e8f0ff,stroke:#6688cc
    style outbound fill:#fff0e8,stroke:#cc8844
```

`StateProxy` holds a priority-100 subscription to `state_changed` events. Its cache updates before any app handler sees the event. `self.states.*` always reflects the current state at handler invocation time.

Outbound calls go through the per-app `Api` handle. Single-entity reads use `ApiResource` over REST. Service calls and bulk state reads use `WebsocketService` over WebSocket.

### Failure behavior

| Failure | Behavior |
|---|---|
| WS disconnect | `WebsocketService` retries with exponential jitter. `ServiceWatcher` restarts the service if `serve()` fails, within the TRANSIENT budget (5 restarts / 300 s). |
| Auth failure | `InvalidAuthError` is a `FatalError` subclass. The `Service` base class catches it, calls `handle_crash()`, and `ServiceWatcher` triggers an immediate shutdown. |
| Handler timeout | Logged; invocation recorded as timed-out. |
| DB write failure | `CommandExecutor` retries up to 3 times, then drops the record with a counter increment. |

## Service Dependencies

### `depends_on` ClassVar

Services declare startup dependencies as a class-level `ClassVar`. The framework reads these declarations at construction time and computes a topological startup order.

```python
--8<-- "pages/core-concepts/snippets/index_depends_on.py"
```

`depends_on` scoping is intentional: only direct children of the `Hassette` root participate. Per-app resources (`Bus`, `Scheduler`, `Api`, `StateManager`) are not services and do not declare `depends_on`.

### Wave-Based Ordering

The dependency graph partitions into topological levels. All services in a wave start concurrently. The framework waits for every service in a wave to signal readiness before advancing. Shutdown runs in reverse wave order.

A `ValueError` with the full cycle path raises at construction time if the dependency graph contains a cycle.

### Framework Dependency Graph

```mermaid
graph BT
    accTitle: Service Dependency Graph
    accDescr: Wave-based startup order, wave 0 at the top

    subgraph wave0["Wave 0 — No Dependencies"]
        DB[DatabaseService]
        WS[WebsocketService]
    end

    subgraph wave1["Wave 1"]
        BUS[BusService]
        SCHED[SchedulerService]
        CMD[CommandExecutor]
        API[ApiResource]
        LOG[LoggingService]
        TQS[TelemetryQueryService]
    end

    subgraph wave2["Wave 2"]
        SP[StateProxy]
        SW[ServiceWatcher]
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

    BUS --> DB
    SCHED --> DB
    CMD --> DB
    LOG --> DB
    TQS --> DB
    API --> WS
    SW --> BUS
    SP --> WS & API & BUS & SCHED
    AH --> WS & API & BUS & SCHED & SP
    RQS --> BUS & SP & AH & LOG
    WEB --> RQS & TQS

    style wave0 fill:#e8f0ff,stroke:#6688cc
    style wave1 fill:#dde8f8,stroke:#6688cc
    style wave2 fill:#d0e0f0,stroke:#6688cc
    style wave3 fill:#c4d8e8,stroke:#6688cc
    style wave4 fill:#b8d0e0,stroke:#6688cc
    style wave5 fill:#acc8d8,stroke:#6688cc
```

Shutdown proceeds in reverse wave order. `WebApiService` stops first. `DatabaseService` and `WebsocketService` stop last.

## Component Ownership

Every component is a `Resource` in a parent/child tree rooted at the `Hassette` instance. Apps receive four lightweight handles (`Bus`, `Scheduler`, `Api`, `StateManager`) that delegate to shared framework services.

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
        LoggingService
        ServiceWatcher
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

    style infra fill:#f0f8e8,stroke:#88aa66
    style core fill:#fff0e8,stroke:#cc8844
    style web fill:#f0f8e8,stroke:#88aa66
    style apps fill:#fff0e8,stroke:#cc8844
    style perapp fill:#f8f0ff,stroke:#8866cc
```

Per-app handles are thin wrappers around the shared services. When an app shuts down, its `Bus` removes listeners from `BusService` and its `Scheduler` removes jobs from `SchedulerService`. Each handle cleans up its own registrations. The shared services continue running for other apps.

## EventStreamService: Constructor-Time Dependency

`EventStreamService` has no `depends_on` because its streams are created synchronously in `__init__`, before the lifecycle begins. The `Hassette` root registers `EventStreamService` before `BusService`, ensuring the receive stream exists when `BusService` is constructed. This ordering is structural, not declared through `depends_on`.

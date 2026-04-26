# Architecture

Hassette has a lot of moving parts, but at its core it’s simple: everything revolves around **apps**, **events**, and **resources**.

- **Apps** are what you write. They respond to events and manipulate resources.
- **Events** describe what happened—state changes, service calls, lifecycle transitions, or scheduled triggers.
- **Resources** are everything else: API clients, the event bus, the scheduler, etc.

## Hassette Architecture

At runtime, the `Hassette` class is the entry point. It receives a `HassetteConfig` instance that defines where to find Home Assistant, your apps, and related configuration.

Each app you write receives four lightweight handles — these are the objects you call in your automation code:

- [`Api`](api/index.md) – call Home Assistant services, read entity states, and subscribe to WebSocket messages.
- [`Bus`](bus/index.md) – subscribe to state change events and service call events.
- [`Scheduler`](scheduler/index.md) – schedule one-off and recurring jobs.
- [`States`](states/index.md) – read the current state of any Home Assistant entity, instantly, from local memory.

??? note "Internal services"
    Hassette starts several infrastructure services to support your apps. These are not user-facing and do not appear in your app code, but they may appear in debug logs:

    - `WebsocketService` – maintains the WebSocket connection and dispatches events.
    - `ApiResource` – typed interface to Home Assistant's REST and WebSocket APIs.
    - `BusService` – routes events from the socket to subscribed apps.
    - `SchedulerService` – runs scheduled jobs.
    - `AppHandler` – discovers, loads, and initializes your apps. Configured via [Application Configuration](configuration/applications.md).
    - `StateProxy` – tracks state changes and provides a consistent view of Home Assistant states.
    - `DatabaseService` – persistent telemetry storage, configurable via `db_*` fields in [global settings](configuration/global.md).
    - `WebApiService` – serves the REST API, healthcheck, and web UI.
    - `RuntimeQueryService` – provides live runtime data (events, logs, metrics) to the web UI.
    - `TelemetryQueryService` – serves historical telemetry (invocations, executions, errors) from the database.
    - `EventStreamService` – event delivery pipeline.
    - `ServiceWatcher` – monitors and restarts failed services.
    - `FileWatcherService` – detects code changes for hot reload.
    - `SessionManager` – tracks session lifecycle.
    - `CommandExecutor` – dispatches app management commands.

### Diagrams

These diagrams illustrate the architecture and relationships between the main components. Diagrams 1–2 show what Hassette is made of internally; diagram 3 shows the four handles your app code calls directly.

#### 1) High-level flow

```mermaid
flowchart TD
    subgraph ha["Home Assistant"]
        HA["Events + API"]
    end

    subgraph hassette["Hassette"]
        H["Framework"]
    end

    subgraph apps["Your Apps"]
        APPS["Automations"]
    end

    HA <--> H
    H <--> APPS

    style ha fill:#f0f0f0,stroke:#999
    style hassette fill:#fff0e8,stroke:#cc8844
    style apps fill:#e8f0ff,stroke:#6688cc
```

#### 2) Core services inside Hassette

```mermaid
flowchart TD
    H[Hassette]

    subgraph infra["Infrastructure"]
        direction LR
        WS[WebsocketService]
        DB[DatabaseService]
    end

    subgraph core["Core"]
        direction LR
        BUS[BusService]
        SCHED[SchedulerService]
        API[ApiResource]
        STATE[StateProxy]
    end

    subgraph web["Web"]
        direction LR
        WEB[WebApiService]
        RTQ[RuntimeQueryService]
        TQ[TelemetryQueryService]
    end

    subgraph apps["Apps"]
        APPH[AppHandler]
    end

    H --- infra & core & web & apps

    style infra fill:#f0f0f0,stroke:#999
    style core fill:#fff0e8,stroke:#cc8844
    style web fill:#f0f8e8,stroke:#88aa66
    style apps fill:#e8f0ff,stroke:#6688cc
```

#### 3) What each app gets (lightweight handles)

```mermaid
flowchart TD
    subgraph app["App Instance"]
        APP["Your App"]
    end

    subgraph handles["Lightweight Handles"]
        direction LR
        API[Api]
        BUS[Bus]
        SCHED[Scheduler]
        STATES[States]
        CACHE[Cache]
    end

    APP --> API & BUS & SCHED & STATES & CACHE

    style app fill:#e8f0ff,stroke:#6688cc
    style handles fill:#fff0e8,stroke:#cc8844
```

Learn more about writing apps in the [apps](apps/index.md) section.

## Service Dependency Graph

Every internal Hassette service declares which other services it needs to be ready before it can initialize. This declaration drives both startup ordering and shutdown ordering — automatically, without any explicit sequencing code in the services themselves.

### How `depends_on` works

Each service class carries a `depends_on` ClassVar that lists the resource types it depends on:

```python
from typing import ClassVar
from hassette.resources.base import Resource, Service
from hassette.core.database_service import DatabaseService


class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
```

At startup, Hassette validates the full dependency graph and computes a topological initialization order. When a service initializes, it automatically waits for every service in its `depends_on` list to become ready before any of its own lifecycle hooks (`on_initialize`, etc.) run. You do not need to call `wait_for_ready()` yourself — the framework handles it.

`depends_on` is scoped to Hassette's direct children — the top-level services registered with the `Hassette` instance. It is not used for child resources inside a service.

!!! note "Coordinator gate vs. service dependency"
    `Hassette.ready_event` is a separate mechanism from `depends_on`. It signals that the coordinator is ready to begin starting services, but does not guarantee that every service has finished starting. Services like `BusService`, `SchedulerService`, and `FileWatcherService` wait on it before processing user-visible work. Do not confuse this coordinator gate with `depends_on`, which expresses readiness ordering between individual services.

### Initialization and shutdown order

Both startup and shutdown use **wave-based ordering**. The dependency graph is partitioned into levels: level 0 has services with no dependencies, level 1 has services that depend only on level 0, and so on. Each wave starts (or shuts down) concurrently via `asyncio.gather`, but waves execute sequentially — so all dependencies are guaranteed ready before their dependents begin.

Shutdown proceeds in reverse wave order. Services that depend on others shut down first; services depended upon (like `DatabaseService`) shut down last. For example, `AppHandler` shuts down before `StateProxy`, and `StateProxy` shuts down before `WebsocketService`.

### Cycle detection

Hassette validates the dependency graph at construction time. If a cycle exists — for example, service A declares `depends_on = [B]` and B declares `depends_on = [A]` — startup raises a `ValueError` with the full cycle path before any service starts:

```
ValueError: Cycle detected: CommandExecutor → DatabaseService → CommandExecutor
```

Fix cycles by restructuring the dependency so one service no longer needs the other to be ready first.

### Framework dependency graph

The key built-in services have the following declared dependencies, organized by startup wave:

```mermaid
graph BT
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

An arrow from A to B means "A depends on B" — B must be ready before A initializes. Shutdown proceeds in reverse wave order.

For detailed diagrams of each subsystem's internals, see [System Internals](internals.md).

!!! note "EventStreamService"
    `EventStreamService` has a constructor-time dependency: it passes a receive stream to `BusService` at Hassette construction time, before any service initializes. This structural ordering is enforced by child registration order rather than `depends_on`, which only expresses runtime readiness dependencies.

## Deep Dive

For detailed Mermaid diagrams of every subsystem's internals — event routing, scheduler heap, state caching, the resource lifecycle state machine, and more — see [System Internals](internals.md).

## See Also

- [Apps](apps/index.md) – how apps fit into the overall architecture.
- [Bus](bus/index.md) – subscribing to and handling events.
- [Scheduler](scheduler/index.md) – scheduling jobs and intervals.
- [API](api/index.md) – interacting with Home Assistant.
- [States](states/index.md) – working with state models.
- [Configuration](configuration/index.md) – Hassette and app configuration.
- [Web UI](../web-ui/index.md) – browser-based monitoring and management.
- [API Reference](../../reference/) – full auto-generated reference for all public modules.

??? note "Advanced Topics — read these after you're comfortable with the basics"
    Once you've written a few automations, these topics give you more control:

    - [Dependency Injection](bus/dependency-injection.md) – automatic event data extraction and type conversion.
    - [Type Registry](../advanced/type-registry.md) – automatic value type conversion system.
    - [State Registry](../advanced/state-registry.md) – domain to state model mapping.
    - [Custom States](../advanced/custom-states.md) – defining your own state classes.

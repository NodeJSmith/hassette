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
graph LR
    HA[Home Assistant] <--> H[Hassette]
    H --> APPS[Your Apps]
    APPS --> H
```

#### 2) Core services inside Hassette

```mermaid
graph TB
    H[Hassette]
    H --> WS[WebsocketService]
    H --> API[ApiResource]
    H --> BUS[BusService]
    H --> SCHED[SchedulerService]
    H --> APPS[AppHandler]
    H --> STATE[StateProxy]
    H --> DB[DatabaseService]
    H --> WEB[WebApiService]
    H --> RTQ[RuntimeQueryService]
    H --> TQ[TelemetryQueryService]
```

#### 3) What each app gets (lightweight handles)

```mermaid
graph TB
    APP[App Instance]
    APP --> API[Api]
    APP --> BUS[Bus]
    APP --> SCHED[Scheduler]
    APP --> STATES[States]
```

Learn more about writing apps in the [apps](apps/index.md) section.

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

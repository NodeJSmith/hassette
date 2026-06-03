# Architecture

Hassette connects Home Assistant to the automations app authors write. It receives events over a WebSocket and routes them through an event bus to subscribed handlers. Each app gets typed access to the Home Assistant API, entity states, and a scheduler.

Three concepts underpin everything: apps, events, and resources.

- Apps run the automation logic. Each app subscribes to events, schedules tasks, and calls Home Assistant services.
- Events describe what happened: a state change, a service call, a scheduled trigger, or a lifecycle transition.
- Resources are the objects apps use to act: the bus, the scheduler, the API client, and the state cache.

## Per-App Handles

Every [`App`](apps/index.md) instance carries four handles. These are the objects automation code calls directly.

- [`Api`](api/index.md) calls Home Assistant services, reads and writes entity states, and sends WebSocket commands.
- [`Bus`](bus/index.md) delivers Home Assistant events (state changes, service calls, component loads) to subscribed handlers.
- [`Scheduler`](scheduler/index.md) runs functions at a specified time, after a delay, or on a recurring interval.
- [`States`](states/index.md) returns the current state of any Home Assistant entity from a local in-memory cache.

Each handle is scoped to the app instance. Listeners registered on one app's `Bus` do not fire for another app. Jobs scheduled on one app's `Scheduler` cancel independently of all others.

```mermaid
flowchart TD
    subgraph app["App Instance"]
        APP["App"]
    end

    subgraph handles["Handles"]
        direction LR
        API[Api]
        BUS[Bus]
        SCHED[Scheduler]
        STATES[States]
    end

    APP --> API & BUS & SCHED & STATES

    style app fill:#e8f0ff,stroke:#6688cc
    style handles fill:#fff0e8,stroke:#cc8844
```

## How It Fits Together

Hassette sits between Home Assistant and the apps it runs.

```mermaid
flowchart TD
    subgraph ha["Home Assistant"]
        HA["Events + API"]
    end

    subgraph hassette["Hassette"]
        H["Framework"]
    end

    subgraph apps["Apps"]
        APPS["Automations"]
    end

    HA <--> H
    H <--> APPS

    style ha fill:#f0f0f0,stroke:#999
    style hassette fill:#fff0e8,stroke:#cc8844
    style apps fill:#e8f0ff,stroke:#6688cc
```

Inside the framework, infrastructure handles the WebSocket connection, persistent telemetry, and the web UI. Core services (the bus, scheduler, API client, and state cache) connect that infrastructure to app code. App management discovers, loads, and initializes each app class.

```mermaid
flowchart TD
    H[Hassette]

    subgraph infra["Infrastructure"]
        direction LR
        WS[WebSocket]
        DB[Database]
    end

    subgraph core["Core"]
        direction LR
        BUS[Bus]
        SCHED[Scheduler]
        API[Api]
        STATE[States]
    end

    subgraph web["Web"]
        direction LR
        WEB[Web UI]
        RTQ[Runtime Queries]
        TQ[Telemetry Queries]
    end

    subgraph apps["Apps"]
        APPH[App Management]
    end

    H --- infra & core & web & apps

    style infra fill:#f0f0f0,stroke:#999
    style core fill:#fff0e8,stroke:#cc8844
    style web fill:#f0f8e8,stroke:#88aa66
    style apps fill:#e8f0ff,stroke:#6688cc
```

## Startup

Hassette starts services in dependency order. `Api`, `Bus`, `Scheduler`, and `States` are all ready before `on_initialize` runs on any app. [Resource Lifecycle & Supervision](internals/lifecycle.md) covers the full startup sequence and service lifecycle.

## Topics

- [Apps](apps/index.md): the `App` base class, lifecycle hooks, and `AppConfig`.
- [Bus](bus/index.md): subscribing to events, filtering, handler options.
- [Scheduler](scheduler/index.md): triggers, job groups, jitter.
- [API](api/index.md): service calls, state reads, WebSocket commands.
- [States](states/index.md): state models, domain access, type conversion.
- [Configuration](configuration/index.md): Hassette and app configuration.
- [Web UI](../web-ui/index.md): browser-based monitoring and management.
- [System Internals](internals/lifecycle.md): service lifecycle, startup sequence, resource hierarchy.
- [API Reference](../../reference/index.md): auto-generated reference for all public modules.

??? note "Advanced Topics"
    - [Dependency Injection](bus/dependency-injection.md): automatic event data extraction and type conversion.
    - [Type Registry](states/type-registry.md): automatic value type conversion system.
    - [State Registry](states/state-registry.md): domain to state model mapping.
    - [Custom States](states/custom-states.md): defining custom state classes for non-standard entity types.

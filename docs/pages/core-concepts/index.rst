Core Concepts
================

Hassette has a lot of moving parts, but at its core it’s simple: everything revolves around ``apps``, ``events``, and ``resources``.

- **Apps** are what *you* write. They’re automations that respond to events and manipulate resources.
- **Events** are things that happen — Home Assistant state changes, service calls, Hassette lifecycle events, or scheduled triggers.
- **Resources** are everything else: the building blocks that make things work — the API clients, event bus, scheduler, and so on.

In essence, **apps** interact with **resources** to get things done in response to **events**.


Hassette Architecture
----------------------

At runtime, all these parts connect through a small, layered system:

The core entry point is the ``Hassette`` class, which spins up when you run the ``hassette`` command.
It receives a ``HassetteConfig`` instance that defines where to find Home Assistant, your apps, and related configuration.

``Hassette`` bootstraps and manages the core services:

- ``WebsocketService`` — Maintains the WebSocket connection to Home Assistant and dispatches incoming events.
- ``ApiResource`` — Provides a typed interface to Home Assistant’s REST and WebSocket APIs.
- ``BusService`` — Routes events from the WebSocket to apps that subscribe to them.
- ``SchedulerService`` — Runs scheduled jobs for apps.
- ``AppHandler`` — Discovers, loads, and initializes your apps.
- *(and others)*

Each app is loaded through the ``AppHandler`` and receives its own lightweight interfaces:

- ``Api`` — A thin wrapper around ``ApiResource`` for making API calls.
- ``Bus`` — Used to subscribe to and handle events.
- ``Scheduler`` — Used to schedule and manage jobs.

Diagram
________

The below diagram illustrates how these components interact at a high level:

.. mermaid::

    graph TB
        subgraph "Home Assistant"
            HA[Home Assistant<br/>Server]
        end

        subgraph "Hassette"
            HASSETTE[Hassette]

            subgraph "Core Services"
                WS[WebsocketService<br/>Receives Events]
                API_RES[ApiResource<br/>Handles Requests]
                BUS_SVC[BusService<br/>Routes Events]
                SCHED_SVC[SchedulerService<br/>Runs Jobs]
                APP_HDL[AppHandler<br/>Manages Apps]
            end
        end

        subgraph "Your Apps"
            APP1[Your Custom Apps]

            subgraph "Each App Has"
                APP_API[Api]
                APP_BUS[Bus]
                APP_SCHED[Scheduler]
            end
        end

        %% Connections
        HA -.->|Events via WebSocket| WS
        WS --> BUS_SVC
        BUS_SVC --> APP_BUS

        HASSETTE --> WS
        HASSETTE --> API_RES
        HASSETTE --> BUS_SVC
        HASSETTE --> SCHED_SVC
        HASSETTE --> APP_HDL

        APP_HDL --> APP1

        APP1 -.-> APP_API
        APP1 -.-> APP_BUS
        APP1 -.-> APP_SCHED

        APP_API --> API_RES
        APP_BUS --> BUS_SVC
        APP_SCHED --> SCHED_SVC

        API_RES <-.->|REST/WebSocket| HA

        %% Styling
        classDef haStyle fill:#4CAF50,stroke:#2E7D32,stroke-width:2px,color:#fff
        classDef coreStyle fill:#2196F3,stroke:#1565C0,stroke-width:2px,color:#fff
        classDef serviceStyle fill:#FF9800,stroke:#E65100,stroke-width:2px,color:#fff
        classDef appStyle fill:#9C27B0,stroke:#6A1B9A,stroke-width:2px,color:#fff

        class HA haStyle
        class HASSETTE coreStyle
        class WS,API_RES,BUS_SVC,SCHED_SVC,APP_HDL serviceStyle
        class APP1,APP_API,APP_BUS,APP_SCHED appStyle


Learn more about writing apps in the :doc:`apps core concept <./apps/index>` section.

See Also
--------

- :doc:`./apps/index` — how apps fit into the overall architecture
- :doc:`./scheduler/index` — more on scheduling jobs and intervals
- :doc:`./bus/index` — more on subscribing to and handling events
- :doc:`./api/index` — more on interacting with Home Assistant's APIs
- :doc:`./configuration/index` — Hassette and app configuration


.. raw:: html

   <style>
     .wy-nav-content {
         max-width: 1400px;
     }
     .mermaid {
         max-width: 100%;
         overflow-x: auto;
         margin: 1.5em 0;
     }
     .mermaid svg {
         max-width: none;
         height: auto;
     }
   </style>

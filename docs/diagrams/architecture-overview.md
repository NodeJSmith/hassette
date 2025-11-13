# Hassette Architecture Overview

This diagram provides a high-level overview of how Hassette components fit together.

```mermaid
graph TB
    subgraph "Home Assistant"
        HA[Home Assistant Instance]
        HA_REST[REST API]
        HA_WS[WebSocket API]
    end

    subgraph "Hassette Core"
        HASSETTE[Hassette<br/>Main Runtime]

        subgraph "Core Services"
            WS[WebsocketService<br/>Event Stream]
            API_RES[ApiResource<br/>REST & WS Client Manager]
            BUS_SVC[BusService<br/>Event Router]
            SCHED_SVC[SchedulerService<br/>Job Scheduler]
            APP_HDL[AppHandler<br/>App Lifecycle Manager]
            HEALTH[HealthService<br/>Status Monitor]
        end

        subgraph "Shared Resources"
            TB[TaskBucket<br/>Background Tasks]
            STREAM[Memory Stream<br/>Event Queue]
        end
    end

    subgraph "User Apps"
        APP1[App Instance 1]
        APP2[App Instance 2]
        APP3[App Instance N]

        subgraph "App Resources"
            APP_API[Api<br/>HA Interaction]
            APP_BUS[Bus<br/>Event Handlers]
            APP_SCHED[Scheduler<br/>Time-based Jobs]
            APP_TB[TaskBucket<br/>Background Work]
        end
    end

    %% Home Assistant connections
    HA_WS -.->|WebSocket Events| WS
    WS -->|Parse & Forward| STREAM
    API_RES <-->|REST Requests| HA_REST
    API_RES <-->|WS Messages| HA_WS

    %% Core service connections
    HASSETTE -->|Initializes & Manages| WS
    HASSETTE -->|Initializes & Manages| API_RES
    HASSETTE -->|Initializes & Manages| BUS_SVC
    HASSETTE -->|Initializes & Manages| SCHED_SVC
    HASSETTE -->|Initializes & Manages| APP_HDL
    HASSETTE -->|Initializes & Manages| HEALTH

    %% Event flow
    STREAM -->|Events| BUS_SVC
    BUS_SVC -->|Dispatch to Owner| APP_BUS

    %% App management
    APP_HDL -->|Loads & Initializes| APP1
    APP_HDL -->|Loads & Initializes| APP2
    APP_HDL -->|Loads & Initializes| APP3

    %% App resource usage
    APP1 -.->|Uses| APP_API
    APP1 -.->|Subscribes| APP_BUS
    APP1 -.->|Schedules| APP_SCHED
    APP1 -.->|Background Tasks| APP_TB

    APP2 -.->|Uses| APP_API
    APP3 -.->|Uses| APP_API

    %% Resource delegation
    APP_API -->|Delegates to| API_RES
    APP_BUS -->|Registers with| BUS_SVC
    APP_SCHED -->|Registers with| SCHED_SVC
    APP_TB -->|Managed by| TB

    %% Scheduler and health
    SCHED_SVC -->|Executes Jobs| APP_SCHED
    HEALTH -->|Monitors| HASSETTE
    HEALTH -->|Monitors| WS
    HEALTH -->|Monitors| APP_HDL

    %% Styling
    classDef haStyle fill:#4CAF50,stroke:#2E7D32,stroke-width:2px,color:#fff
    classDef coreStyle fill:#2196F3,stroke:#1565C0,stroke-width:2px,color:#fff
    classDef serviceStyle fill:#FF9800,stroke:#E65100,stroke-width:2px,color:#fff
    classDef appStyle fill:#9C27B0,stroke:#6A1B9A,stroke-width:2px,color:#fff
    classDef resourceStyle fill:#607D8B,stroke:#37474F,stroke-width:2px,color:#fff

    class HA,HA_REST,HA_WS haStyle
    class HASSETTE coreStyle
    class WS,API_RES,BUS_SVC,SCHED_SVC,APP_HDL,HEALTH serviceStyle
    class APP1,APP2,APP3 appStyle
    class APP_API,APP_BUS,APP_SCHED,APP_TB,TB,STREAM resourceStyle
```

## Component Descriptions

### Home Assistant
- **Home Assistant Instance**: The external Home Assistant server that Hassette connects to
- **REST API**: HTTP endpoints for querying states, calling services, etc.
- **WebSocket API**: Real-time event stream for state changes and system events

### Hassette Core
- **Hassette**: Main runtime that initializes and coordinates all services and resources
- **WebsocketService**: Maintains WebSocket connection to Home Assistant, receives all events
- **ApiResource**: Manages HTTP client and WebSocket for API calls (shared by all apps)
- **BusService**: Routes incoming events to appropriate app handlers based on subscriptions
- **SchedulerService**: Executes time-based and cron-style jobs for all apps
- **AppHandler**: Discovers, loads, and manages the lifecycle of user apps
- **HealthService**: Monitors system health and service status
- **Memory Stream**: Internal queue for passing events from WebSocket to BusService
- **TaskBucket**: Manages background tasks with proper lifecycle and cleanup

### User Apps
- **App Instances**: User-defined automation apps (e.g., lighting controller, notification handler)
- **Api**: Per-app interface for calling Home Assistant services, querying states, etc.
- **Bus**: Per-app event bus for subscribing to state changes and other events
- **Scheduler**: Per-app scheduler for time-based automations
- **TaskBucket**: Per-app background task manager

## Data Flow

### Event Flow (Home Assistant → Apps)
1. Home Assistant emits an event (e.g., light state change)
2. WebsocketService receives the event via WebSocket
3. Event is parsed and sent to Memory Stream
4. BusService reads from stream and routes to subscribed apps
5. App's Bus resource invokes registered handler functions

### API Flow (Apps → Home Assistant)
1. App calls method on its Api resource (e.g., `turn_on_light()`)
2. Api delegates to shared ApiResource
3. ApiResource sends REST request or WebSocket message
4. Home Assistant processes the request
5. Response returned to app

### Scheduling Flow
1. App registers job with its Scheduler resource (e.g., "run daily at 6 AM")
2. Scheduler registers with shared SchedulerService
3. SchedulerService executes job at scheduled time
4. Job runs in app's context with proper error handling

## Key Design Principles

1. **Async-First**: All I/O operations are async for efficient concurrency
2. **Resource Hierarchy**: Services and resources form a tree with clear ownership
3. **Event-Driven**: Apps react to Home Assistant events via the event bus
4. **Type Safety**: Strong typing throughout with Pydantic models and TypeVars
5. **Isolation**: Each app has its own resource instances for clean separation
6. **Shared Infrastructure**: Common services (WebSocket, HTTP client) are shared for efficiency

# Hassette Architecture

A high-level overview of how Hassette connects your apps to Home Assistant.

```mermaid
graph TB
    subgraph "Home Assistant"
        HA[Home Assistant<br/>Server]
    end

    subgraph "Hassette Core"
        HASSETTE[Hassette Runtime]

        subgraph "Core Services"
            WS[WebsocketService<br/>Receives Events]
            API_RES[ApiResource<br/>Handles Requests]
            BUS_SVC[BusService<br/>Routes Events]
            SCHED_SVC[SchedulerService<br/>Runs Jobs]
            APP_HDL[AppHandler<br/>Manages Apps]
        end
    end

    subgraph "Your Apps"
        APP1[Lighting App]
        APP2[Notification App]
        APP3[Your Custom Apps]

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
    APP_HDL --> APP2
    APP_HDL --> APP3

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
    class APP1,APP2,APP3,APP_API,APP_BUS,APP_SCHED appStyle
```

## How It Works

### Event Flow (Home Assistant → Your Apps)
1. **Home Assistant** emits events (state changes, service calls, etc.)
2. **WebsocketService** maintains connection and receives all events
3. **BusService** routes events to apps that subscribed to them
4. Your app's **Bus** resource delivers events to your handler functions

### API Flow (Your Apps → Home Assistant)
1. Your app calls methods on its **Api** resource (turn on lights, get states, etc.)
2. **ApiResource** sends the request to Home Assistant
3. Response comes back to your app

### Scheduling
1. Your app schedules jobs via its **Scheduler** resource
2. **SchedulerService** executes jobs at the right time
3. Your scheduled function runs

### App Management
- **AppHandler** discovers, loads, and initializes your apps from config
- Each app gets its own **Api**, **Bus**, and **Scheduler** instances
- Apps are isolated from each other but share the core infrastructure

## Key Concepts

- **Hassette Runtime**: Coordinates everything and manages the lifecycle
- **Core Services**: Shared infrastructure (WebSocket, API client, event routing, scheduling)
- **Your Apps**: Where you write automation logic using simple, typed APIs
- **App Resources**: Each app has dedicated Api, Bus, and Scheduler for clean separation

# Apps — Overview

**Status:** Exists (186 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Structure
App[Config] generic, five handles (bus, scheduler, api, states, cache), logger.

### H2: Defining an App
Minimal app example, AppConfig usage.

### H2: Dates and Times
`whenever` library usage for date/time in apps.

### H2: Core Capabilities
Brief overview linking to each capability's page:
#### H3: Reacting to Events
#### H3: Run Recurring Jobs
#### H3: Check Entity States
#### H3: Call Services
#### H3: Persist Data Between Restarts
#### H3: Run Background Tasks and Blocking Code

### H2: Restricting to a Single App During Development
`@only_app` decorator to isolate one app without editing config.

### H2: Broadcasting Events Between Apps
`Bus.emit()` for inter-app communication.

### H2: Synchronous Apps
`SyncApp` variant for simple scripts.

### H2: Next Steps
Links to Lifecycle, Configuration, Task Bucket.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 15 files in `apps/snippets/` | Review | Check each for voice, DI-first alignment |

## Cross-Links

- **Links to:** Lifecycle, Configuration, Task Bucket, Bus overview, Scheduler overview, States overview, API overview, Cache overview
- **Linked from:** Architecture, First Automation, Recipes

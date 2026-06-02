# Apps — Overview

**Status:** Exists (186 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Structure
App[Config] generic, five handles (bus, scheduler, api, states, cache), logger.

### H2: Defining an App
Minimal app example, AppConfig usage.

*Absorbs content from the former `apps/configuration.md` (34 lines):*
- AppConfig subclass with `SettingsConfigDict` and `env_prefix`
- Base fields: `instance_name`, `log_level`, `app_key` (reserved prefix validator)
- `extra="allow"` (arbitrary config without defined fields), `env_ignore_empty=True`
- Secrets & env vars via Pydantic `BaseSettings`
- Link to Configuration/Applications for the TOML registration side

### H2: Dates and Times
`whenever` library usage for date/time in apps. `self.now()` returns the current `ZonedDateTime`.

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
`AppSync` variant for apps where async adds unnecessary complexity or doesn't fit the libraries in use (e.g., `requests`, blocking database clients).

### H2: Next Steps
Links to all sibling and handle pages: Lifecycle, Configuration, Task Bucket, Bus overview, Scheduler overview, States overview, API overview, Cache overview.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 15 files in `apps/snippets/` | Review | Check each for voice, DI-first alignment |

## Cross-Links

- **Links to:** Lifecycle, Configuration, Task Bucket, Bus overview, Scheduler overview, States overview, API overview, Cache overview
- **Linked from:** Architecture, First Automation, Recipes

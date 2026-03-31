# config_log_level Convention

Establishes rules for how Resources get their log level from configuration.

## The Rule

Every concrete Resource subclass must override `config_log_level`. No concrete class should fall through to the base `Resource.config_log_level` (which returns the global `config.log_level`).

**Exception:** `Hassette` itself (the root coordinator) intentionally uses the base-class default, since the global `log_level` is the correct scope for the root.

There are three modes for a `config_log_level` override:

| Mode | When to use | Example |
|------|------------|---------|
| **Dedicated field** | The Resource is a primary service registered directly on Hassette, with its own user-visible log output that operators will want to tune independently | `DatabaseService` → `database_service_log_level` |
| **Cross-bound** | The Resource is a helper/child of a primary service and its logs are conceptually part of that service's output | `AppLifecycleService` → `app_handler_log_level` |
| **App-owned** | The Resource is owned by an App and should inherit the app's log level | `Bus` (when owned by an App) → app's log level |

### Deciding which mode

1. **Is this Resource registered directly on Hassette?** → Dedicated field.
2. **Is this Resource a child of another service?** → Cross-bind to the parent service's field.
3. **Is this Resource owned by an App?** → Use the app's log level.

For case 3 (app-owned), see [#462](https://github.com/NodeJSmith/hassette/issues/462) — the current implementation cross-binds app-owned Bus/Scheduler instances to the service-level field. The future direction is for app-owned resources to inherit from their owning app.

## Current Inventory

### Hassette-registered services (dedicated fields)

| Resource | Config field |
|----------|-------------|
| `DatabaseService` | `database_service_log_level` |
| `BusService` | `bus_service_log_level` |
| `SchedulerService` | `scheduler_service_log_level` |
| `AppHandler` | `app_handler_log_level` |
| `WebApiService` | `web_api_log_level` |
| `WebSocketService` | `websocket_log_level` |
| `ServiceWatcher` | `service_watcher_log_level` |
| `FileWatcherService` | `file_watcher_log_level` |
| `TaskBucket` | `task_bucket_log_level` |
| `CommandExecutor` | `command_executor_log_level` |
| `StateProxy` | `state_proxy_log_level` |
| `Api` | `api_log_level` |

### Cross-bound resources

| Resource | Binds to | Rationale |
|----------|----------|-----------|
| `ApiResource` | `api_log_level` | HTTP transport layer for Api |
| `AppLifecycleService` | `app_handler_log_level` | Child of AppHandler |
| `RuntimeQueryService` | `web_api_log_level` | Query service under WebApi |
| `TelemetryQueryService` | `web_api_log_level` | Query service under WebApi |
| `SessionManager` | `database_service_log_level` | Manages DB sessions |
| `EventStreamService` | `bus_service_log_level` | Owns the event channel feeding the bus |
| `WebUiWatcherService` | `file_watcher_log_level` | File watcher for web UI assets |
| `_ScheduledJobQueue` | `scheduler_service_log_level` | Child of SchedulerService |

### App-owned resources

| Resource | Current binding | Future (#462) |
|----------|----------------|---------------|
| `App` | `app_config.log_level` (falls back to `apps_log_level`) | (already correct) |
| `Bus` (app-owned) | `bus_service_log_level` | App's log level |
| `Scheduler` (app-owned) | `scheduler_service_log_level` | App's log level |
| `Api` (app-owned) | `api_log_level` | App's log level |
| `StateManager` (app-owned) | `state_proxy_log_level` | App's log level |
| `ApiSyncFacade` (app-owned) | `api_log_level` | App's log level |

## Construction-Time Snapshot

`_setup_logger()` runs once in `Resource.__init__()`. The log level is read from config at construction time and set on the Python `Logger` object. If `config.reload()` changes a log level field afterward, existing Resources will not pick up the change until they are restarted.

This is a known limitation. Runtime log level changes will require a config-change listener or explicit re-application — tracked separately from this convention.

## Type Annotations

All `config_log_level` overrides must return `-> LOG_LEVEL_TYPE`. The base class property is annotated the same way so Pyright enforces consistency on all overrides.

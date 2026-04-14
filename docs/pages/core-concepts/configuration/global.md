# Global Settings

Global settings control how Hassette runs and connects to Home Assistant. These are defined under the `[hassette]` table in `hassette.toml`.

**Most users only need the first few sections.** The settings are organized from most to least commonly configured:

- **Common** — [Connection](#connection-settings), [Runtime](#runtime-settings), [Storage](#storage-settings), [Web UI](#web-ui-settings), [Database](#database-settings)
- **Advanced** — [Timeouts](#timeout-settings), [Scheduler](#scheduler-settings), [Logging](#logging-settings), [Bus Filtering](#bus-filtering-settings), [Production](#production-settings), [App Detection](#app-detection-settings), [Service Restart Policy](#service-restart-policy), [Other Advanced](#other-advanced-settings)

---

## Connection Settings

- **`base_url`** (string): Home Assistant URL.
    - Default: `http://127.0.0.1:8123`
    - Must include the scheme (`http://` or `https://`) and port.

- **`verify_ssl`** (boolean): Whether to verify SSL certificates when connecting to Home Assistant.
    - Default: `true`
    - Set to `false` if using self-signed certificates.

- **`import_dot_env_files`** (boolean): Whether to load `.env` file contents into `os.environ`.
    - This is useful to allow apps to access these values without needing to import the file.
    - Default: `true`

## Runtime Settings

- **`app_dir`** (string): Directory containing your app modules.
    - Default: `.` (current directory)
    - Example: `src/apps`

- **`dev_mode`** (boolean): Enable development features.
    - **Heuristics**: If not explicitly set, Hassette detects dev mode by checking for:
        - `debugpy` or `pydevd` in `sys.modules`
        - `sys.gettrace()` being set
        - `sys.flags.dev_mode` being enabled
    - **Features Enabled**:
        - Automatic file watching and hot reloading.
        - Extended timeouts for tasks and connections.
        - Skipping some strict startup pre-checks.

## Storage Settings

- **`data_dir`** (string): Directory where Hassette stores persistent data.
    - Default: platform-dependent. Docker: `/data`. Linux: `~/.local/share/hassette/vN/`. macOS: `~/Library/Application Support/hassette/vN/`. Where `N` is the installed major version.
    - Override with `HASSETTE__DATA_DIR` environment variable for a stable path across upgrades.
    - Used for [app cache](../cache/index.md) storage and other data files.
    - Each resource class gets its own subdirectory: `{data_dir}/{ClassName}/cache/`

    !!! warning "Major version upgrades"
        The default path includes the major version number. Upgrading to a new major version changes the path, which means the telemetry database and cache data appear to "disappear." Set an explicit `data_dir` if you need persistence across major upgrades.

- **`default_cache_size`** (integer): Maximum size in bytes for each resource's disk cache.
    - Default: `104857600` (100 MiB)
    - When the limit is reached, least recently used items are automatically evicted.
    - See [App Cache](../cache/index.md) for usage details.

**Example:**

```toml
--8<-- "pages/core-concepts/configuration/snippets/storage_example.toml"
```

## Web UI Settings

These settings control the [web UI](../../web-ui/index.md) and the underlying web API service.

- **`run_web_api`** (boolean): Whether to run the web API service (REST API, healthcheck, and UI backend).
    - Default: `true`

- **`run_web_ui`** (boolean): Whether to serve the browser dashboard. Only used when `run_web_api` is `true`.
    - Default: `true`

- **`web_api_host`** (string): Host to bind the web API server to.
    - Default: `0.0.0.0`

- **`web_api_port`** (integer): Port to run the web API server on.
    - Default: `8126`
    - The UI is accessible at `http://<host>:<port>/ui/`

- **`web_api_cors_origins`** (tuple): Allowed CORS origins for the web API.
    - Default: `("http://localhost:3000", "http://localhost:5173")`

- **`web_api_event_buffer_size`** (integer): Maximum number of recent events to keep in the ring buffer.
    - Default: `500`

- **`web_api_log_buffer_size`** (integer): Maximum number of log entries to keep in the ring buffer.
    - Default: `2000`

- **`web_api_job_history_size`** (integer): Maximum number of job execution records to keep in memory.
    - Default: `1000`

- **`web_ui_hot_reload`** (boolean): Watch web UI static files for changes and push live reloads to the browser via WebSocket. CSS changes are hot-swapped without a page reload; JS changes trigger a full reload.
    - Default: `false`

**Example:**

```toml
--8<-- "pages/core-concepts/configuration/snippets/web_ui_example.toml"
```

## Database Settings

These settings control the persistent telemetry database. See [Database & Telemetry](../database-telemetry.md) for details on what is stored.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `db_path` | path or null | `null` | Path to the SQLite database file. Defaults to `{data_dir}/hassette.db` when not set. |
| `db_retention_days` | integer | `7` | Number of days to retain execution records (handler invocations, job executions). Minimum: 1. |
| `db_max_size_mb` | float | `500` | Maximum database file size in MB. When exceeded, oldest execution records are deleted. Set to `0` to disable the size limit. |

**Example:**

```toml
--8<-- "pages/core-concepts/configuration/snippets/database_example.toml"
```

## Timeout Settings

These settings control how long Hassette waits for various operations before giving up.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `startup_timeout_seconds` | integer | `10` | Time to wait for all Hassette resources to start. |
| `app_startup_timeout_seconds` | integer | `20` | Time to wait for an individual app to start. |
| `app_shutdown_timeout_seconds` | integer | `10` | Time to wait for an individual app to shut down. |
| `total_shutdown_timeout_seconds` | integer | `30` | Maximum wall-clock seconds for the entire Hassette shutdown process. |
| `websocket_authentication_timeout_seconds` | integer | `10` | Time to wait for WebSocket authentication to complete. |
| `websocket_response_timeout_seconds` | integer | `5` | Time to wait for a response from the WebSocket. |
| `websocket_connection_timeout_seconds` | integer | `5` | Time to wait for the WebSocket connection to establish. |
| `websocket_total_timeout_seconds` | integer | `30` | Total time for WebSocket operations to complete. |
| `websocket_heartbeat_interval_seconds` | integer | `30` | Interval for WebSocket keepalive pings. |

## Scheduler Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `scheduler_min_delay_seconds` | integer | `1` | Minimum sleep interval for the scheduler loop. Prevents busy-waiting when jobs fire in rapid succession. |
| `scheduler_max_delay_seconds` | integer | `30` | Maximum sleep interval for the scheduler loop. Bounds how long the scheduler may wait before checking for due jobs. |
| `scheduler_default_delay_seconds` | integer | `15` | Default sleep interval used when no jobs are imminently due. |

## Logging Settings

Hassette supports per-service log levels for each of its 13 internal services. Each field falls back to the global `log_level` setting (default: `INFO`).

See [Log Level Tuning](../../advanced/log-level-tuning.md) for the full field list, precedence rules, and examples.

## Bus Filtering Settings

Filter out noisy events at the bus level before they reach your apps.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `bus_excluded_domains` | tuple of strings | `()` | Domains whose events are skipped; supports glob patterns (e.g. `"sensor"`, `"media_*"`). |
| `bus_excluded_entities` | tuple of strings | `()` | Entity IDs whose events are skipped; supports glob patterns. |

**Example:**

```toml
--8<-- "pages/core-concepts/configuration/snippets/bus_filter_example.toml"
```

## Production Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `allow_reload_in_prod` | boolean | `false` | Enable file watching and automatic app reloads in production mode. Manual app management (start/stop/reload via API) is always available. |
| `allow_only_app_in_prod` | boolean | `false` | Allow the `only_app` decorator in production mode. |

## App Detection Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `autodetect_apps` | boolean | `true` | Automatically discover apps in the app directory. |
| `run_app_precheck` | boolean | `true` | Run app precheck before starting. If any apps fail to load, Hassette does not start. |
| `allow_startup_if_app_precheck_fails` | boolean | `false` | Allow Hassette to start even if the app precheck fails. Generally not recommended. |
| `extend_autodetect_exclude_dirs` | tuple of strings | `()` | Additional directories to exclude from app auto-detection. **Use this instead of `autodetect_exclude_dirs`** — it adds to the defaults rather than replacing them. |
| `autodetect_exclude_dirs` | tuple of strings | *(built-in list)* | Full list of excluded directories. Setting this directly **replaces** the defaults (`.git`, `__pycache__`, `.venv`, etc.), which is usually not what you want. |

!!! warning
    If you need to exclude additional directories from app auto-detection, always use `extend_autodetect_exclude_dirs`. Setting `autodetect_exclude_dirs` directly will remove the default exclusions, causing Hassette to scan `.git`, `__pycache__`, virtual environments, and other directories that should be ignored.

## Advanced Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `hassette_event_buffer_size` | integer | `1000` | Buffer capacity of the internal event channel used to route events to the bus. |
| `asyncio_debug_mode` | boolean | `false` | Enable asyncio debug mode. |
| `watch_files` | boolean | `true` | Watch files for changes and reload apps automatically. |

## Service Restart Policy

These settings control automatic restart behavior when an internal service crashes.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `service_restart_max_attempts` | integer | `5` | Maximum restart attempts before giving up. |
| `service_restart_backoff_seconds` | float | `2.0` | Initial delay between restart attempts. |
| `service_restart_max_backoff_seconds` | float | `60.0` | Maximum delay between restart attempts. |
| `service_restart_backoff_multiplier` | float | `2.0` | Multiplier applied after each failed attempt. |
| `service_restart_readiness_timeout_seconds` | float | `10.0` | Seconds to wait for a restarted service to become ready. |

## Other Advanced Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `resource_shutdown_timeout_seconds` | integer | *(same as `app_shutdown_timeout_seconds`)* | Per-phase timeout for resource shutdown. |
| `state_proxy_poll_interval_seconds` | integer | `30` | Interval to poll Home Assistant for state updates (supplements WebSocket events). |
| `disable_state_proxy_polling` | boolean | `false` | Disable state polling entirely (rely only on WebSocket events). |
| `db_migration_timeout_seconds` | integer | `120` | Maximum seconds to wait for database migrations at startup. |
| `file_watcher_debounce_milliseconds` | integer | `3000` | Debounce time for file watcher events. |
| `file_watcher_step_milliseconds` | integer | `500` | Time to wait for additional file changes before emitting an event. Works with the debounce to batch rapid saves. |
| `task_cancellation_timeout_seconds` | integer | `5` | Time to wait for tasks to cancel before forcing. |
| `scheduler_behind_schedule_threshold_seconds` | integer | `5` | Threshold before a "behind schedule" warning is logged. |
| `run_sync_timeout_seconds` | integer | `6` | Default timeout for synchronous function calls. |

## Basic Example

```toml
--8<-- "pages/core-concepts/configuration/snippets/basic_config.toml"
```

## See Also

- [Authentication](auth.md) - Tokens and secrets
- [Applications](applications.md) - App registration and configuration
- [App Cache](../cache/index.md) - Using the disk cache

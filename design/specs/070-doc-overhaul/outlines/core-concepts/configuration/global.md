# Configuration — Global Settings

**Status:** Exists (313 lines), dense reference, voice polish needed
**Voice mode:** Reference — tabular, terse, system-as-subject

## Outline

Long reference page documenting every global setting in hassette.toml. Keep current structure — it's a lookup reference.

### H2: Connection Settings
`base_url` (single URL, default `http://127.0.0.1:8123`), `verify_ssl`, `token` location.

### H2: Runtime Settings
`allow_reload_in_prod`, `apps.directory`, `strict_lifecycle`, `asyncio_debug_mode`, `allow_only_app_in_prod`, `run_app_precheck`, `allow_startup_if_app_precheck_fails`, `import_dot_env_files`.

### H2: Storage Settings
`data_dir` (cache paths derived automatically from `data_dir/<ClassName>/cache`; no `cache_dir` config key).

### H2: Web UI Settings
`web_api.run`, `web_api.run_ui`, `web_api.ui_hot_reload`, `web_api.host`, `web_api.port`, `web_api.cors_origins`, `web_api.event_buffer_size`, `web_api.log_buffer_size`, `web_api.job_history_size`.

### H2: Database Settings
`database.path`, `database.retention_days`.

### H2: Lifecycle Settings
`LifecycleConfig`: `startup_timeout_seconds`, `app_startup_timeout_seconds`, `app_shutdown_timeout_seconds`, `event_handler_timeout_seconds`, `error_handler_timeout_seconds`, `run_sync_timeout_seconds`, `resource_shutdown_timeout_seconds`, `total_shutdown_timeout_seconds`, `registration_await_timeout`, `task_cancellation_timeout_seconds`.

### H2: File Watcher Settings
`FileWatcherConfig`: `watch_files`, `debounce_milliseconds`, `step_milliseconds`.

### H2: WebSocket Settings
`connect_retry_*` fields (initial connect retries within the service), `early_drop_*` fields (fast reconnect on brief disconnects), and `max_recovery_seconds` (caps total wall-clock recovery time). Note: these are separate from the ServiceWatcher restart budget.

### H2: Timeout Settings
Per-item overrides, disabling, limitations.

### H2: Scheduler Settings
Default scheduler configuration.

### H2: Logging Settings
`LoggingConfig`: `log_format` (`"auto"`, `"console"`, `"json"`), `log_persistence_level`, `log_retention_days`, `log_queue_max`, 13 per-service log levels (`database_service`, `bus_service`, `scheduler_service`, `app_handler`, `web_api`, `websocket`, `service_watcher`, `file_watcher`, `task_bucket`, `command_executor`, `apps`, `state_proxy`, `api`), and debug flags (`all_events`, `all_hass_events`, `all_hassette_events`).

### H2: Bus Filtering Settings
`bus_excluded_domains`, `bus_excluded_entities`, `hassette_event_buffer_size`.

### H2: State Proxy Settings
`state_proxy_poll_interval_seconds`, `disable_state_proxy_polling`.

### H2: Cache Settings
`default_cache_size` (default 100 MiB). No other cache config — paths are derived from `data_dir`.

### H2: Service Restart Policy
Note: `RestartSpec` is a code-level class attribute on `Service` subclasses, NOT a `hassette.toml` setting. Document the defaults here for reference but clarify it is configured in code.

### H2: Basic Example
Complete hassette.toml example.

## Snippet Inventory

No code snippets — TOML examples are inline.

## Cross-Links

- **Links to:** Configuration overview, Operating/Log Levels (log settings detail)
- **Linked from:** Configuration overview, Docker Setup, Operating

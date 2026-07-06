"""Legacy flat config key → nested path migration mapping.

When HassetteConfig was restructured from flat fields to nested Pydantic models,
all config fields moved under group prefixes (e.g., ``log_level`` → ``logging.log_level``).
Users upgrading from the flat config format will have unrecognized keys silently
absorbed by ``extra="allow"``. This mapping enables detection and warning.
"""

LEGACY_KEY_MIGRATION: dict[str, str] = {
    # database
    "db_path": "database.path",
    "db_retention_days": "database.retention_days",
    "db_max_size_mb": "database.max_size_mb",
    "db_migration_timeout_seconds": "database.migration_timeout_seconds",
    "db_write_queue_max": "database.write_queue_max",
    "telemetry_write_queue_max": "database.telemetry_write_queue_max",
    # websocket
    "websocket_authentication_timeout_seconds": "websocket.authentication_timeout_seconds",
    "websocket_response_timeout_seconds": "websocket.response_timeout_seconds",
    "websocket_connection_timeout_seconds": "websocket.connection_timeout_seconds",
    "websocket_total_timeout_seconds": "websocket.total_timeout_seconds",
    "websocket_heartbeat_interval_seconds": "websocket.heartbeat_interval_seconds",
    "websocket_connect_retry_max_attempts": "websocket.connect_retry_max_attempts",
    "websocket_connect_retry_initial_wait_seconds": "websocket.connect_retry_initial_wait_seconds",
    "websocket_connect_retry_max_wait_seconds": "websocket.connect_retry_max_wait_seconds",
    "websocket_early_drop_stable_window_seconds": "websocket.early_drop_stable_window_seconds",
    "websocket_early_drop_max_retries": "websocket.early_drop_max_retries",
    "websocket_early_drop_backoff_initial_seconds": "websocket.early_drop_backoff_initial_seconds",
    "websocket_early_drop_backoff_max_seconds": "websocket.early_drop_backoff_max_seconds",
    "websocket_max_recovery_seconds": "websocket.max_recovery_seconds",
    # logging
    "log_level": "logging.log_level",
    "log_format": "logging.log_format",
    "log_queue_max": "logging.log_queue_max",
    "log_persistence_level": "logging.log_persistence_level",
    "log_retention_days": "logging.log_retention_days",
    "log_all_events": "logging.all_events",
    "log_all_hass_events": "logging.all_hass_events",
    "log_all_hassette_events": "logging.all_hassette_events",
    "database_service_log_level": "logging.database_service",
    "bus_service_log_level": "logging.bus_service",
    "scheduler_service_log_level": "logging.scheduler_service",
    "app_handler_log_level": "logging.app_handler",
    "web_api_log_level": "logging.web_api",
    "websocket_log_level": "logging.websocket",
    "service_watcher_log_level": "logging.service_watcher",
    "file_watcher_log_level": "logging.file_watcher",
    "task_bucket_log_level": "logging.task_bucket",
    "command_executor_log_level": "logging.command_executor",
    "apps_log_level": "logging.apps",
    "state_proxy_log_level": "logging.state_proxy",
    "api_log_level": "logging.api",
    # lifecycle
    "startup_timeout_seconds": "lifecycle.startup_timeout_seconds",
    "app_startup_timeout_seconds": "lifecycle.app_startup_timeout_seconds",
    "app_shutdown_timeout_seconds": "lifecycle.app_shutdown_timeout_seconds",
    "resource_shutdown_timeout_seconds": "lifecycle.resource_shutdown_timeout_seconds",
    "total_shutdown_timeout_seconds": "lifecycle.total_shutdown_timeout_seconds",
    "registration_await_timeout": "lifecycle.registration_await_timeout",
    "event_handler_timeout_seconds": "lifecycle.event_handler_timeout_seconds",
    "error_handler_timeout_seconds": "lifecycle.error_handler_timeout_seconds",
    "run_sync_timeout_seconds": "lifecycle.run_sync_timeout_seconds",
    "task_cancellation_timeout_seconds": "lifecycle.task_cancellation_timeout_seconds",
    # web_api
    "run_web_api": "web_api.run",
    "run_web_ui": "web_api.run_ui",
    "web_ui_hot_reload": "web_api.ui_hot_reload",
    "web_api_host": "web_api.host",
    "web_api_port": "web_api.port",
    "web_api_cors_origins": "web_api.cors_origins",
    "web_api_log_buffer_size": "web_api.log_buffer_size",
    "web_api_job_history_size": "web_api.job_history_size",
    # app
    "app_dir": "apps.directory",
    "autodetect_apps": "apps.autodetect",
    "extend_autodetect_exclude_dirs": "apps.extend_exclude_dirs",
    "autodetect_exclude_dirs": "apps.exclude_dirs",
    # scheduler
    "scheduler_min_delay_seconds": "scheduler.min_delay_seconds",
    "scheduler_max_delay_seconds": "scheduler.max_delay_seconds",
    "scheduler_default_delay_seconds": "scheduler.default_delay_seconds",
    "scheduler_behind_schedule_threshold_seconds": "scheduler.behind_schedule_threshold_seconds",
    "scheduler_job_timeout_seconds": "scheduler.job_timeout_seconds",
    # file_watcher
    "watch_files": "file_watcher.watch_files",
    "file_watcher_debounce_milliseconds": "file_watcher.debounce_milliseconds",
    "file_watcher_step_milliseconds": "file_watcher.step_milliseconds",
}

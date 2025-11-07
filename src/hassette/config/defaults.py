from typing import Any

AUTODETECT_EXCLUDE_DIRS_DEFAULT = (".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".git")


PROD_DEFAULTS = dict(
    app_shutdown_timeout_seconds=10,
    app_startup_timeout_seconds=20,
    file_watcher_debounce_milliseconds=3_000,
    file_watcher_step_milliseconds=500,
    health_service_port=8126,
    import_dot_env_files=True,
    run_app_precheck=True,
    allow_startup_if_app_precheck_fails=False,
    run_health_service=True,
    run_sync_timeout_seconds=6,
    scheduler_default_delay_seconds=15,
    scheduler_max_delay_seconds=30,
    scheduler_min_delay_seconds=1,
    startup_timeout_seconds=10,
    task_cancellation_timeout_seconds=5,
    watch_files=False,
    websocket_authentication_timeout_seconds=10,
    websocket_connection_timeout_seconds=5,
    websocket_heartbeat_interval_seconds=30,
    websocket_response_timeout_seconds=5,
    websocket_total_timeout_seconds=30,
    log_all_events=False,
    log_all_hass_events=False,
    log_all_hassette_events=False,
    allow_reload_in_prod=False,
    allow_only_app_in_prod=False,
    auto_detect_exclude_dirs=AUTODETECT_EXCLUDE_DIRS_DEFAULT,
)


DEV_DEFAULTS = dict(
    app_shutdown_timeout_seconds=20,
    app_startup_timeout_seconds=40,
    file_watcher_debounce_milliseconds=6_000,
    file_watcher_step_milliseconds=1000,
    health_service_port=8126,
    import_dot_env_files=True,
    run_app_precheck=True,
    allow_startup_if_app_precheck_fails=True,
    run_health_service=True,
    run_sync_timeout_seconds=12,
    scheduler_default_delay_seconds=30,
    scheduler_max_delay_seconds=60,
    scheduler_min_delay_seconds=2,
    startup_timeout_seconds=20,
    task_cancellation_timeout_seconds=10,
    watch_files=True,
    websocket_authentication_timeout_seconds=20,
    websocket_connection_timeout_seconds=10,
    websocket_heartbeat_interval_seconds=60,
    websocket_response_timeout_seconds=10,
    websocket_total_timeout_seconds=60,
    log_all_events=False,
    log_all_hass_events=False,
    log_all_hassette_events=False,
    allow_reload_in_prod=False,
    allow_only_app_in_prod=False,
    auto_detect_exclude_dirs=AUTODETECT_EXCLUDE_DIRS_DEFAULT,
)


def get_default_dict(dev: bool = False) -> dict[str, Any]:
    """Get the default configuration dictionary.

    Args:
        dev: Whether to use development defaults.

    Returns:
        The default configuration dictionary.
    """
    return DEV_DEFAULTS if dev else PROD_DEFAULTS

"""Configuration endpoint."""

from fastapi import APIRouter

from hassette.web.dependencies import HassetteDep
from hassette.web.models import ConfigResponse

router = APIRouter(tags=["config"])

_CONFIG_SAFE_FIELDS: set[str] = {
    "dev_mode",
    "log_level",
    "base_url",
    "run_web_api",
    "run_web_ui",
    "web_api_host",
    "web_api_port",
    "web_api_cors_origins",
    "web_api_event_buffer_size",
    "web_api_log_buffer_size",
    "web_api_job_history_size",
    "web_api_log_level",
    "autodetect_apps",
    "startup_timeout_seconds",
    "app_startup_timeout_seconds",
    "app_shutdown_timeout_seconds",
    "watch_files",
    "file_watcher_debounce_milliseconds",
    "scheduler_min_delay_seconds",
    "scheduler_max_delay_seconds",
    "scheduler_default_delay_seconds",
    "asyncio_debug_mode",
    "allow_reload_in_prod",
    "web_ui_hot_reload",
}


@router.get("/config", response_model=ConfigResponse)
async def get_config(hassette: HassetteDep) -> ConfigResponse:
    """Return sanitized hassette configuration (allowlisted fields only)."""
    raw = hassette.config.model_dump(include=_CONFIG_SAFE_FIELDS)
    # The three Path fields are intentionally outside _CONFIG_SAFE_FIELDS: model_dump() would
    # serialize them as PosixPath objects, not strings.  We inject them manually after str() cast
    # so that ConfigResponse receives plain strings regardless of the underlying Path type.
    raw["app_dir"] = str(hassette.config.app_dir)
    raw["data_dir"] = str(hassette.config.data_dir)
    raw["config_dir"] = str(hassette.config.config_dir)
    return ConfigResponse.model_validate(raw)

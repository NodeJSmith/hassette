"""Configuration endpoint."""

from fastapi import APIRouter

from hassette.web.dependencies import HassetteDep
from hassette.web.models import (
    AppsConfigResponse,
    ConfigResponse,
    FileWatcherConfigResponse,
    LifecycleConfigResponse,
    LoggingConfigResponse,
    SchedulerConfigResponse,
    WebApiConfigResponse,
)

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
async def get_config(hassette: HassetteDep) -> ConfigResponse:
    """Return sanitized hassette configuration organized by config group."""
    cfg = hassette.config
    return ConfigResponse(
        dev_mode=cfg.dev_mode,
        base_url=cfg.base_url,
        asyncio_debug_mode=cfg.asyncio_debug_mode,
        allow_reload_in_prod=cfg.allow_reload_in_prod,
        data_dir=str(cfg.data_dir),
        config_dir=str(cfg.config_dir),
        web_api=WebApiConfigResponse(
            run=cfg.web_api.run,
            run_ui=cfg.web_api.run_ui,
            ui_hot_reload=cfg.web_api.ui_hot_reload,
            host=cfg.web_api.host,
            port=cfg.web_api.port,
            cors_origins=list(cfg.web_api.cors_origins),
            event_buffer_size=cfg.web_api.event_buffer_size,
            log_buffer_size=cfg.web_api.log_buffer_size,
            job_history_size=cfg.web_api.job_history_size,
        ),
        logging=LoggingConfigResponse(
            log_level=cfg.logging.log_level,
            web_api=cfg.logging.web_api,
        ),
        lifecycle=LifecycleConfigResponse(
            startup_timeout_seconds=cfg.lifecycle.startup_timeout_seconds,
            app_startup_timeout_seconds=cfg.lifecycle.app_startup_timeout_seconds,
            app_shutdown_timeout_seconds=cfg.lifecycle.app_shutdown_timeout_seconds,
        ),
        apps=AppsConfigResponse(
            autodetect=cfg.apps.autodetect,
            directory=str(cfg.apps.directory),
        ),
        scheduler=SchedulerConfigResponse(
            min_delay_seconds=cfg.scheduler.min_delay_seconds,
            max_delay_seconds=cfg.scheduler.max_delay_seconds,
            default_delay_seconds=cfg.scheduler.default_delay_seconds,
        ),
        file_watcher=FileWatcherConfigResponse(
            watch_files=cfg.file_watcher.watch_files,
            debounce_milliseconds=cfg.file_watcher.debounce_milliseconds,
        ),
    )

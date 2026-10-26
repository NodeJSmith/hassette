"""One-time startup tasks that run while ``Hassette`` wires its services, never on a config reload."""

import logging

from dotenv import load_dotenv

from hassette.config import HassetteConfig
from hassette.exceptions import AppPrecheckFailedError
from hassette.utils.app_utils import app_startup_warnings, run_apps_pre_check


def run_startup_tasks(config: HassetteConfig, logger: logging.Logger) -> None:
    """Load ``.env`` files, validate app manifests, log the startup summary, and run the app precheck.

    ``stacklevel=3`` on the summary lines attributes them to ``wire_services()``'s caller.

    Raises:
        AppPrecheckFailedError: If the app precheck fails and
            ``allow_startup_if_app_precheck_fails`` is false.
    """
    if config.import_dot_env_files:
        for env_file in config.env_files:
            if env_file.exists():
                logger.debug("Loading environment variables from %s", env_file)
                load_dotenv(env_file)

    config.set_validated_app_manifests()

    config_files = sorted(config.toml_files | config.env_files)
    logger.info("Config files read: %s", ", ".join(map(str, config_files)) or "none", stacklevel=3)

    logger.info("Apps directory: %s", config.apps.directory, stacklevel=3)
    for warning in app_startup_warnings(config.apps, config_files=config_files, cwd=config.locations.cwd):
        logger.warning(warning, stacklevel=3)

    active_apps = [app for app in config.apps.manifests.values() if app.enabled]
    logger.info("Found %d active apps", len(active_apps), stacklevel=3)

    inactive_apps = [app for app in config.apps.manifests.values() if not app.enabled]
    if inactive_apps:
        logger.info("Found %d inactive apps", len(inactive_apps), stacklevel=3)

    try:
        run_apps_pre_check(config)
    except AppPrecheckFailedError:
        if not config.allow_startup_if_app_precheck_fails:
            logger.error("App precheck failed and startup is not allowed to continue. Raising exception.")
            raise
        logger.warning("App precheck failed, but startup will continue due to configuration setting.")

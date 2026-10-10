"""Run command — starts the Hassette framework server."""

import asyncio
import errno
import shlex
import sys
from logging import getLogger
from pathlib import Path
from typing import Annotated, Any

from cyclopts import Parameter

from hassette.cli.client import emit_usage_error
from hassette.cli.context import DEFAULT_CLI_CONTEXT, CLIContextParam
from hassette.config.config import HassetteConfig
from hassette.config.helpers import get_log_level
from hassette.exceptions import AppPrecheckFailedError, ConfigError, FatalError
from hassette.logging_ import enable_basic_logging
from hassette.server import main as run_server
from hassette.utils.app_utils import missing_apps_dir_warning

LOGGER = getLogger("hassette.cli")

EX_CONFIG = 78
"""sysexits.h ``EX_CONFIG``: the configuration must be edited before a restart can succeed.

Raised for a `ConfigError` and for a failed app precheck (an app file must be edited). Supervisors
key on it (systemd ``RestartPreventExitStatus=78``, the add-on's s6 ``finish`` script).
"""


def split_app_keys(values: list[str]) -> tuple[str, ...]:
    """Flatten repeated and comma-separated ``--app`` values into unique keys, preserving order."""
    keys = [key.strip() for value in values for key in value.split(",") if key.strip()]
    return tuple(dict.fromkeys(keys))


def cmd_run(
    token: Annotated[str | None, Parameter(name=["--token", "-t"], help="Home Assistant access token.")] = None,
    base_url: Annotated[
        str | None, Parameter(name=["--ha-url", "-u"], help="URL of the Home Assistant instance to connect to.")
    ] = None,
    verify_ssl: Annotated[
        bool | None,
        Parameter(
            name=["--ha-verify-ssl"],
            help="Whether to verify SSL certificates for the Home Assistant connection.",
            negative=[],
        ),
    ] = None,
    dev_mode: Annotated[
        bool | None,
        Parameter(name=["--dev-mode"], help="Enable developer mode.", negative=[]),
    ] = None,
    app: Annotated[
        list[str] | None,
        Parameter(
            name=["--app", "-a"],
            help="Run only this app key, excluding all others. Repeatable, or comma-separated.",
            negative=[],
        ),
    ] = None,
    check: Annotated[
        bool,
        Parameter(
            name=["--check"],
            help="Load and check the configuration, print the resolved CONFIG_DIR, CONFIG_HOME and APPS_DIR "
            "as shell-quoted KEY=VALUE lines, and exit without importing apps or starting Hassette.",
            negative=[],
        ),
    ] = False,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Start the Hassette framework server."""
    init_kwargs: dict[str, Any] = ctx.config_location_kwargs()
    if token is not None:
        init_kwargs["token"] = token
    if base_url is not None:
        init_kwargs["base_url"] = base_url
    if verify_ssl is not None:
        init_kwargs["verify_ssl"] = verify_ssl
    if dev_mode is not None:
        init_kwargs["dev_mode"] = dev_mode
    if app:
        only = split_app_keys(app)
        if not only:
            emit_usage_error("--app requires at least one non-empty app key")
        init_kwargs["only_apps"] = only

    if check:
        check_config(init_kwargs)
        return

    # The server logs its whole run to stdout, as a service should; until here the bootstrap
    # fallback wrote to stderr so commands whose stdout is data keep it clean.
    enable_basic_logging(get_log_level(), log_format="auto")

    config: HassetteConfig | None = None
    try:
        config = HassetteConfig(**init_kwargs)
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        # Only reachable before server.main() installs its own SIGINT handler, or if that
        # registration itself fails — once installed, Ctrl+C is handled there, not here.
        LOGGER.info("Keyboard interrupt received, shutting down")
    except ConfigError as exc:
        LOGGER.error("Invalid configuration: %s", exc)
        raise SystemExit(EX_CONFIG) from None
    except AppPrecheckFailedError as exc:
        LOGGER.error("App precheck failed: %s", exc)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
        raise SystemExit(EX_CONFIG) from None
    except FatalError as exc:
        LOGGER.error("Fatal error occurred: %s", exc)
        LOGGER.error("Hassette is shutting down due to a fatal error")
        raise SystemExit(1) from None
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE and config is not None:
            LOGGER.error("Port %s is already in use — is another hassette instance running?", config.web_api.port)
            raise SystemExit(1) from None
        LOGGER.exception("OS error in Hassette: %s", exc)
        raise
    except Exception as exc:
        LOGGER.exception("Unexpected error in Hassette: %s", exc)
        raise


def check_config(init_kwargs: dict[str, Any]) -> None:
    """Build and check the config as ``hassette run`` would, then print the resolved locations for ``docker_start.sh``.

    Beyond construction's checks, it requires a token and validates the app entries written in the
    config. Autodetected apps are skipped, since finding them imports app modules.

    On success, stdout carries only shell-quoted ``KEY=VALUE`` lines, which the entrypoint
    evaluates: the resolved, absolute ``CONFIG_DIR``, ``CONFIG_HOME`` and ``APPS_DIR``. The
    entrypoint proceeds only on exit 0 with all three present. Nothing else may reach stdout:
    ``hassette.__main__.entrypoint`` sends bootstrap logging to stderr, and apps aren't imported.

    A config error prints nothing to stdout and exits 78. Its message is printed to stderr as plain
    text, not logged, so its lines stay readable when stderr isn't a terminal (where logging renders
    JSON). A missing apps directory is a warning, printed the same way, with startup's hint when the
    path was likely written relative to the working directory instead of its config file.
    """
    try:
        config = HassetteConfig(**init_kwargs)
        config.require_token()
        config.check_explicit_app_manifests()
    except ConfigError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        raise SystemExit(EX_CONFIG) from None
    # apps aren't detected here, so only a missing directory is reported, not an empty one
    if warning := missing_apps_dir_warning(
        config.apps.directory, config_files=config.toml_files | config.env_files, cwd=config.locations.cwd
    ):
        print(f"Warning: {warning}", file=sys.stderr)
    print_shell_var("CONFIG_DIR", config.config_dir)
    print_shell_var("CONFIG_HOME", config.locations.config_home)
    print_shell_var("APPS_DIR", config.apps.directory.resolve())


def print_shell_var(name: str, value: str | Path) -> None:
    """Print ``NAME=value`` with the value shell-quoted, for ``docker_start.sh`` to ``eval``."""
    print(f"{name}={shlex.quote(str(value))}")

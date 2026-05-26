"""Hassette CLI — cyclopts App setup, default command, and subcommand registration."""

import asyncio
from importlib.metadata import PackageNotFoundError, version
from logging import getLogger
from typing import Annotated, Any, Literal

from cyclopts import App, Group, Parameter

import hassette.cli.globals as cli_globals
from hassette.app.app_config import AppConfig
from hassette.cli.commands.app import cmd_app, cmd_app_activity, cmd_app_config, cmd_app_health, cmd_app_source
from hassette.cli.commands.job import cmd_job
from hassette.cli.commands.listener import cmd_listener
from hassette.cli.commands.log import cmd_execution, cmd_log
from hassette.cli.commands.misc import cmd_config, cmd_event, cmd_service
from hassette.cli.commands.status import cmd_dashboard, cmd_status, cmd_telemetry
from hassette.config.config import HassetteConfig
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.server import main as run_server

LOGGER = getLogger("hassette.cli")

# ---------------------------------------------------------------------------
# Version string
# ---------------------------------------------------------------------------

try:
    _version = version("hassette")
except PackageNotFoundError:
    _version = "unknown"

# ---------------------------------------------------------------------------
# Root App
# ---------------------------------------------------------------------------

app = App(
    name="hassette",
    version=_version,
    version_flags=["--version", "-v"],
    help="Hassette — async-first Home Assistant automation framework.",
)

app.meta.group_parameters = Group("Global Options", sort_key=0)
app.register_install_completion_command(add_to_startup=False)


@app.command(name="--generate-completion")
def generate_completion(
    shell: Annotated[
        Literal["zsh", "bash", "fish"] | None,
        Parameter(help="Shell to generate completions for. Auto-detected if omitted."),
    ] = None,
) -> None:
    """Print shell completion script to stdout."""
    print(app.generate_completion(shell=shell))


status_app = App(name="status", help="Show system status.")
app.command(status_app)

apps_app = App(name="app", help="List and inspect apps.")
app.command(apps_app)

listener_app = App(name="listener", help="List listeners and invocation history.")
app.command(listener_app)

job_app = App(name="job", help="List scheduled jobs and execution history.")
app.command(job_app)

log_app = App(name="log", help="Show recent log entries.")
app.command(log_app)

execution_app = App(name="execution", help="Show logs for a specific execution.")
app.command(execution_app)

event_app = App(name="event", help="Show recent HA events.")
app.command(event_app)

config_app = App(name="config", help="Show current configuration.")
app.command(config_app)

service_app = App(name="service", help="List available HA services.")
app.command(service_app)

telemetry_app = App(name="telemetry", help="Show telemetry status.")
app.command(telemetry_app)

dashboard_app = App(name="dashboard", help="Show app dashboard grid.")
app.command(dashboard_app)

status_app.default(cmd_status)
telemetry_app.default(cmd_telemetry)
dashboard_app.default(cmd_dashboard)
config_app.default(cmd_config)
service_app.default(cmd_service)
event_app.default(cmd_event)

apps_app.default(cmd_app)
apps_app.command(cmd_app_health, name="health")
apps_app.command(cmd_app_activity, name="activity")
apps_app.command(cmd_app_config, name="config")
apps_app.command(cmd_app_source, name="source")

listener_app.default(cmd_listener)
job_app.default(cmd_job)

log_app.default(cmd_log)
execution_app.default(cmd_execution)

# ---------------------------------------------------------------------------
# Meta app — global options that apply to all commands
# ---------------------------------------------------------------------------


@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    config_file: Annotated[
        str | None, Parameter(name=["--config-file", "-c"], help="Path to the TOML configuration file.")
    ] = None,
    env_file: Annotated[
        str | None, Parameter(name=["--env-file", "-e", "--env"], help="Path to the .env file.")
    ] = None,
    json: Annotated[bool, Parameter(name=["--json"], help="Output results as JSON.", negative=[])] = False,
) -> None:
    cli_globals.env_file_override = env_file
    cli_globals.config_file_override = config_file
    cli_globals.json_mode = json

    if env_file:
        HassetteConfig.model_config["env_file"] = env_file
        AppConfig.model_config["env_file"] = env_file
    if config_file:
        HassetteConfig.model_config["toml_file"] = config_file

    app(tokens)


# ---------------------------------------------------------------------------
# Default command — starts the framework server (backward compatibility)
# ---------------------------------------------------------------------------


@app.default
def start_server(
    token: Annotated[str | None, Parameter(name=["--token", "-t"], help="Home Assistant access token.")] = None,
    base_url: Annotated[
        str | None, Parameter(name=["--base-url", "-u", "--url"], help="Base URL of the Home Assistant instance.")
    ] = None,
    verify_ssl: Annotated[
        bool | None,
        Parameter(name=["--verify-ssl"], help="Whether to verify SSL certificates.", negative=[]),
    ] = None,
    dev_mode: Annotated[
        bool | None,
        Parameter(name=["--dev-mode"], help="Enable developer mode.", negative=[]),
    ] = None,
) -> None:
    """Start the Hassette framework server."""
    # Build init kwargs — only pass values explicitly provided on the CLI (non-None)
    init_kwargs: dict[str, Any] = {}
    if token is not None:
        init_kwargs["token"] = token
    if base_url is not None:
        init_kwargs["base_url"] = base_url
    if verify_ssl is not None:
        init_kwargs["verify_ssl"] = verify_ssl
    if dev_mode is not None:
        init_kwargs["dev_mode"] = dev_mode

    config = HassetteConfig(**init_kwargs)

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received, shutting down")
    except AppPrecheckFailedError as e:
        LOGGER.error("App precheck failed: %s", e)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
        raise SystemExit(1) from None
    except FatalError as e:
        LOGGER.error("Fatal error occurred: %s", e)
        LOGGER.error("Hassette is shutting down due to a fatal error")
        raise SystemExit(1) from None
    except Exception as e:
        LOGGER.exception("Unexpected error in Hassette: %s", e)
        raise

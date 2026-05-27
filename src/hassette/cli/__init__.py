"""Hassette CLI — cyclopts App setup and subcommand registration."""

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal

from cyclopts import App, Group, Parameter

import hassette.cli.globals as cli_globals
from hassette.app.app_config import AppConfig
from hassette.cli.commands.app import cmd_app, cmd_app_activity, cmd_app_config, cmd_app_health, cmd_app_source
from hassette.cli.commands.job import cmd_job
from hassette.cli.commands.listener import cmd_listener
from hassette.cli.commands.log import cmd_execution, cmd_log
from hassette.cli.commands.misc import cmd_config, cmd_event
from hassette.cli.commands.run import cmd_run
from hassette.cli.commands.status import cmd_dashboard, cmd_status, cmd_telemetry
from hassette.cli.context import CLIContext
from hassette.config.config import HassetteConfig

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
    prog_name = app.name[0] if isinstance(app.name, tuple) else app.name
    script = app.generate_completion(shell=shell)
    if "#compdef" in script:
        script = normalize_zsh_completion(script, prog_name)
    print(script)


def normalize_zsh_completion(script: str, prog_name: str) -> str:
    """Strip the ``_cyclopts_`` namespace prefix from zsh completion functions.

    cyclopts >=4.16 namespaces zsh functions as ``_cyclopts_<prog>`` to avoid
    shadowing zsh builtins. That breaks ``compinit`` autoloading when the file
    is saved as ``_<prog>``. This replaces all occurrences of
    ``_cyclopts_<prog>`` with ``_<prog>`` so the function name matches the
    filename users will write to.
    """
    return script.replace(f"_cyclopts_{prog_name}", f"_{prog_name}")


run_app = App(name="run", help="Start the Hassette framework server.")
app.command(run_app)

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

telemetry_app = App(name="telemetry", help="Show telemetry status.")
app.command(telemetry_app)

dashboard_app = App(name="dashboard", help="Show app dashboard grid.")
app.command(dashboard_app)

run_app.default(cmd_run)
status_app.default(cmd_status)
telemetry_app.default(cmd_telemetry)
dashboard_app.default(cmd_dashboard)
config_app.default(cmd_config)
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
    debug: Annotated[
        bool, Parameter(name=["--debug"], help="Show full HTTP response on CLI errors.", negative=[])
    ] = False,
) -> None:
    cli_globals.env_file_override = env_file
    cli_globals.config_file_override = config_file
    cli_globals.json_mode = json
    cli_globals.debug_mode = debug
    ctx = CLIContext(json_mode=json, debug_mode=debug, env_file_override=env_file, config_file_override=config_file)

    if env_file:
        HassetteConfig.model_config["env_file"] = env_file
        AppConfig.model_config["env_file"] = env_file
    if config_file:
        HassetteConfig.model_config["toml_file"] = config_file

    command, bound, _ignored = app.parse_args(tokens)
    bound.arguments["ctx"] = ctx
    command(*bound.args, **bound.kwargs)

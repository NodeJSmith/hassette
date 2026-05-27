"""CLI context object — frozen dataclass carrying per-invocation configuration."""

from dataclasses import dataclass
from typing import Annotated

from cyclopts import Parameter


@dataclass(frozen=True)
class CLIContext:
    """Immutable configuration for a single CLI invocation.

    Constructed by the meta launcher from parsed global flags and injected into
    every command via ``bound.arguments["ctx"]``.
    """

    json_mode: bool = False
    debug_mode: bool = False
    env_file_override: str | None = None
    config_file_override: str | None = None


CLIContextParam = Annotated[CLIContext, Parameter(parse=False)]

DEFAULT_CLI_CONTEXT = CLIContext()

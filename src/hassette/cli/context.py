"""CLI context object — frozen dataclass carrying per-invocation configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CLIContext:
    """Immutable configuration for a single CLI invocation.

    Constructed by the meta launcher from parsed global flags and injected into
    every command via ``bound.arguments["ctx"]``. Commands declare the parameter
    as ``ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()``; the
    default provides safe values when the launcher doesn't inject (e.g. direct
    test calls).
    """

    json_mode: bool = False
    debug_mode: bool = False
    env_file_override: str | None = None
    config_file_override: str | None = None

"""CLI context object — frozen dataclass carrying per-invocation configuration."""

from dataclasses import dataclass
from pathlib import Path
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
    server_url: str | None = None
    token_file: Path | None = None
    verify_ssl: bool | None = None
    """Tri-state on purpose: ``None`` means "flag not passed, defer to config" — this is what
    lets ``resolve_server_target`` distinguish an explicit ``--no-verify-ssl`` from an unset flag.
    """


CLIContextParam = Annotated[CLIContext, Parameter(parse=False)]

DEFAULT_CLI_CONTEXT = CLIContext()

"""CLI context object — frozen dataclass carrying per-invocation configuration."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from cyclopts import Parameter


@dataclass(frozen=True)
class CLIContext:
    """Immutable configuration for a single CLI invocation.

    Constructed by the meta launcher from parsed global flags and injected into
    every command via ``bound.arguments["ctx"]``.
    """

    json_mode: bool = False
    debug_mode: bool = False
    config_dir: Path | None = None
    """``--config-dir``: the explicit config directory, or None to resolve it from the environment."""
    config_file: Path | None = None
    """``--config-file``: the one TOML file to read instead of searching."""
    env_file: Path | None = None
    """``--env-file``: the one ``.env`` file to read instead of searching."""
    server_url: str | None = None
    token_file: Path | None = None
    verify_ssl: bool | None = None
    """Tri-state on purpose: ``None`` means "flag not passed, defer to config" — this is what
    lets ``resolve_server_target`` distinguish an explicit ``--no-verify-ssl`` from an unset flag.
    """

    def config_location_kwargs(self) -> dict[str, Any]:
        """``HassetteConfig`` kwargs for the location flags; an unpassed ``--config-dir`` stays unset."""
        kwargs: dict[str, Any] = {"config_file": self.config_file, "env_file": self.env_file}
        if self.config_dir is not None:
            kwargs["config_dir"] = self.config_dir
        return kwargs


CLIContextParam = Annotated[CLIContext, Parameter(parse=False)]

DEFAULT_CLI_CONTEXT = CLIContext()

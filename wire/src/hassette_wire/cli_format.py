from dataclasses import dataclass
from typing import Literal

CliFormatStyle = Literal["duration_ms", "duration_s", "uptime", "relative_time", "services", "instance_count"]


@dataclass(frozen=True)
class CliFormat:
    """Annotated metadata marker declaring how a field renders in CLI human mode.

    Attach to model fields via ``Annotated[float, CliFormat("duration_ms")]``.
    The render layer introspects ``model_fields[name].metadata`` and dispatches
    to the matching formatter. JSON serialization is unaffected.
    """

    style: CliFormatStyle
    none_text: str | None = None
    """Display text to use when the field value is ``None``, overriding the render layer's default
    placeholder (``""`` in tables, ``"—"`` in detail panels). E.g. ``none_text="done"`` for a
    ``next_run`` field that reads ``None`` once a one-shot job has fired."""

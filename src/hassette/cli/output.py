"""Rendering layer for hassette CLI commands.

Commands return Pydantic models (or lists of models). This module handles all
output formatting: Rich tables for collections, key-value panels for single
objects, and JSON serialization for structured output.

**stdout cleanliness contract**: In JSON mode, stdout contains exactly one
valid JSON document. All diagnostics, warnings, and "no results" messages go
to the stderr console. The stdout console is used only by render functions.
"""

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from pydantic import BaseModel
from rich.console import Console, OverflowMethod
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from whenever import Instant, OffsetDateTime, PlainDateTime

# ---------------------------------------------------------------------------
# Console instances (stdout data, stderr diagnostics)
# ---------------------------------------------------------------------------

stdout_console = Console(file=sys.stdout, highlight=False)
stderr_console = Console(file=sys.stderr, stderr=True, highlight=False)

# ---------------------------------------------------------------------------
# Built-in field formatters
# ---------------------------------------------------------------------------


def _now() -> float:
    """Return current time as epoch float. Patched in tests for determinism."""
    return time.time()


def fmt_relative_time(value: Any) -> str:
    """Convert an epoch float or ISO string to a relative time string.

    Examples: "2m ago", "1h ago", "just now", "soon".
    """
    if value is None:
        return ""
    try:
        if isinstance(value, (int, float)):
            epoch = float(value)
        else:
            s = str(value)
            try:
                epoch = Instant.parse_iso(s).timestamp()
            except ValueError:
                try:
                    epoch = OffsetDateTime.parse_iso(s).timestamp()
                except ValueError:
                    epoch = PlainDateTime.parse_iso(s).assume_system_tz().timestamp()
        delta = _now() - epoch
        if delta < 0:
            return "soon"
        if delta < 5:
            return "just now"
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta / 60)}m ago"
        if delta < 86400:
            return f"{int(delta / 3600)}h ago"
        return f"{int(delta / 86400)}d ago"
    except (TypeError, ValueError, OSError):
        return str(value)


def fmt_duration(value: Any) -> str:
    """Convert a duration in seconds or milliseconds to a human-readable string.

    Assumes seconds unless the value is greater than 10000, in which case
    assumes milliseconds (heuristic for ms-based telemetry fields).
    Examples: "1.2s", "450ms".
    """
    if value is None:
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    # Heuristic: telemetry duration_ms fields are stored in ms
    if abs(num) >= 10000:
        # Treat as milliseconds
        ms = num
        if abs(ms) < 1000:
            return f"{ms:.0f}ms"
        return f"{ms / 1000:.1f}s"
    # Treat as seconds
    if abs(num) < 1:
        return f"{num * 1000:.0f}ms"
    return f"{num:.1f}s"


def fmt_truncate(max_len: int = 60) -> Callable[[Any], str]:
    """Return a formatter that truncates strings to ``max_len`` characters."""

    def _fmt(value: Any) -> str:
        if value is None:
            return ""
        s = str(value)
        if len(s) > max_len:
            return s[: max_len - 1] + "…"
        return s

    return _fmt


# ---------------------------------------------------------------------------
# Column definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """Maps a model field to a table column for human-mode rendering.

    Args:
        field: Model field name. Supports dot notation for nested fields
            (e.g., ``"status"``). Nested access is done via ``getattr`` chains.
        header: Display header text shown in the table.
        max_width: Optional maximum column width in characters (human mode only).
            Ignored when the output is not a TTY (pipe mode).
        overflow: Rich overflow mode for cells exceeding ``max_width``.
            Defaults to ``"ellipsis"``.
        formatter: Optional callable that transforms the raw field value into a
            display string. Applied only in human mode; JSON mode uses raw values.
    """

    field: str
    header: str
    max_width: int | None = None
    overflow: OverflowMethod = "ellipsis"
    formatter: Callable[[Any], str] | None = dc_field(default=None, compare=False, hash=False)


# ---------------------------------------------------------------------------
# Field extraction helper
# ---------------------------------------------------------------------------


def _extract_field(item: Any, field_path: str) -> Any:
    """Extract a (possibly nested) field value from a model or dict.

    Supports dot notation (e.g., ``"web_api.port"``).
    Returns ``None`` if any segment in the path is missing.
    """
    parts = field_path.split(".")
    value: Any = item
    for part in parts:
        if value is None:
            return None
        value = value.get(part) if isinstance(value, dict) else getattr(value, part, None)
    return value


def _cell_text(value: Any, col: Column) -> str:
    """Convert a raw field value to a table cell string.

    Applies ``col.formatter`` when present. Truncation is handled at the table
    level via ``_build_table`` (``max_width`` is set or cleared based on TTY).
    """
    if col.formatter is not None:
        try:
            return col.formatter(value)
        except Exception:
            return str(value) if value is not None else ""
    if value is None:
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------


def render_table(
    items: list[BaseModel],
    columns: list[Column],
    json_mode: bool,
) -> None:
    """Render a list of Pydantic models as a table or JSON array.

    Args:
        items: List of Pydantic models to render.
        columns: Column definitions for human-mode table output.
        json_mode: When ``True``, serialize to JSON on stdout. When ``False``,
            render a Rich table on stdout.
    """
    if json_mode:
        data = [item.model_dump(mode="json") for item in items]
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        sys.stdout.flush()
        return

    if not items:
        stderr_console.print("No results.", highlight=False)
        return

    is_terminal = stdout_console.is_terminal
    table = _build_table(columns, is_terminal)
    for item in items:
        row = [_cell_text(_extract_field(item, col.field), col) for col in columns]
        table.add_row(*row)

    stdout_console.print(table)


def render_detail(
    item: BaseModel,
    json_mode: bool,
) -> None:
    """Render a single Pydantic model as a key-value panel or JSON object.

    Args:
        item: A Pydantic model to render.
        json_mode: When ``True``, write JSON to stdout. When ``False``,
            render a Rich key-value panel on stdout.
    """
    if json_mode:
        sys.stdout.write(item.model_dump_json(indent=2) + "\n")
        sys.stdout.flush()
        return

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="bold", no_wrap=True)
    table.add_column("value")

    data = item.model_dump(mode="json")
    for key, value in data.items():
        table.add_row(key, _format_detail_value(value))

    panel = Panel(table, title=type(item).__name__, expand=False)
    stdout_console.print(panel)


def render_raw(
    data: dict[str, Any] | list[Any],
    json_mode: bool,
) -> None:
    """Render an untyped dict or list (e.g., services endpoint) as JSON or tree.

    Args:
        data: Raw dict or list to render.
        json_mode: When ``True``, write JSON to stdout. When ``False``,
            render a Rich-formatted JSON view on stdout.
    """
    if json_mode:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        sys.stdout.flush()
        return

    stdout_console.print(JSON(json.dumps(data, indent=2)))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_table(columns: list[Column], is_terminal: bool) -> Table:
    """Build a Rich Table from column definitions.

    In non-TTY (pipe) mode, ``max_width`` is ignored so piped output
    contains full values without truncation.
    """
    table = Table(show_header=True, header_style="bold")
    for col in columns:
        effective_max_width = col.max_width if is_terminal else None
        table.add_column(
            col.header,
            max_width=effective_max_width,
            overflow=col.overflow,
            no_wrap=False,
        )
    return table


def _format_detail_value(value: Any) -> str:
    """Format a value for the key-value detail panel."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)

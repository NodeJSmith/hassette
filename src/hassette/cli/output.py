"""Rendering layer for hassette CLI commands.

Commands return Pydantic models (or lists of models). This module handles all
output formatting: Rich tables for collections, key-value panels for single
objects, and JSON serialization for structured output.

**stdout cleanliness contract**: In JSON mode, stdout contains exactly one
valid JSON document. All diagnostics, warnings, and "no results" messages go
to the stderr console. The stdout console is used only by render functions.
"""

import json
import re
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

from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from hassette.types.types import CliFormat

stdout_console = Console(file=sys.stdout, highlight=False)
stderr_console = Console(file=sys.stderr, stderr=True, highlight=False)


def now_epoch() -> float:
    """Return current time as epoch float. Patched in tests for determinism."""
    return time.time()


def fmt_relative_time(value: Any) -> str:
    """Convert an epoch float or ISO string to a relative time string.

    Examples: "2m ago", "1h ago", "just now", "in 5m".
    """
    if value is None:
        return ""
    try:
        if isinstance(value, (int, float)):
            epoch = float(value)
        else:
            # HA timestamps vary: UTC instant, offset, or bare local datetime
            s = str(value)
            try:
                epoch = Instant.parse_iso(s).timestamp()
            except ValueError:
                try:
                    epoch = OffsetDateTime.parse_iso(s).timestamp()
                except ValueError:
                    epoch = PlainDateTime.parse_iso(s).assume_system_tz().timestamp()
        delta = now_epoch() - epoch
        if delta < 0:
            ahead = -delta
            if ahead < SECONDS_PER_MINUTE:
                return "in <1m"
            if ahead < SECONDS_PER_HOUR:
                return f"in {int(ahead / SECONDS_PER_MINUTE)}m"
            if ahead < SECONDS_PER_DAY:
                return f"in {int(ahead / SECONDS_PER_HOUR)}h"
            return f"in {int(ahead / SECONDS_PER_DAY)}d"
        if delta < 5:
            return "just now"
        if delta < SECONDS_PER_MINUTE:
            return f"{int(delta)}s ago"
        if delta < SECONDS_PER_HOUR:
            return f"{int(delta / SECONDS_PER_MINUTE)}m ago"
        if delta < SECONDS_PER_DAY:
            return f"{int(delta / SECONDS_PER_HOUR)}h ago"
        return f"{int(delta / SECONDS_PER_DAY)}d ago"
    except (TypeError, ValueError, OSError):
        return str(value)


def fmt_duration_ms(value: Any) -> str:
    """Convert a duration in milliseconds to a human-readable string."""
    if value is None:
        return ""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(ms) < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def fmt_duration_s(value: Any) -> str:
    """Convert a duration in seconds to a human-readable string."""
    if value is None:
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num) < 1:
        return f"{num * 1000:.0f}ms"
    return f"{num:.1f}s"


def fmt_next_run(value: Any) -> str:
    """Format a next-run timestamp: ``None`` → ``'done'``, otherwise relative time."""
    if value is None:
        return "done"
    return fmt_relative_time(value)


def fmt_handler_short(value: Any) -> str:
    """Extract just the method name from a fully qualified handler path."""
    if value is None:
        return ""
    return str(value).rsplit(".", 1)[-1]


def fmt_uptime(value: Any) -> str:
    """Convert seconds to a human-readable uptime string (e.g. ``'2h 30m 5s'``)."""
    if value is None:
        return ""
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return str(value)
    if secs < 0:
        return "—"
    if secs < SECONDS_PER_MINUTE:
        return f"{secs:.0f}s"
    if secs < SECONDS_PER_HOUR:
        m, s = divmod(int(secs), SECONDS_PER_MINUTE)
        return f"{m}m {s}s"
    h, remainder = divmod(int(secs), SECONDS_PER_HOUR)
    m, s = divmod(remainder, SECONDS_PER_MINUTE)
    return f"{h}h {m}m {s}s"


CLI_FORMATTERS: dict[str, Callable[[Any], str]] = {
    "duration_ms": fmt_duration_ms,
    "duration_s": fmt_duration_s,
    "uptime": fmt_uptime,
    "relative_time": fmt_relative_time,
}


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
    """Convert a raw field value to a table cell string (blank for None).

    Tables use empty string for missing values so cells stay visually clean.
    Detail panels use ``_format_detail_value`` which shows "—" instead.
    """
    if col.formatter is not None:
        try:
            return col.formatter(value)
        except (TypeError, ValueError):
            return str(value) if value is not None else ""
    if value is None:
        return ""
    return str(value)


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

    Nested sub-models render as labeled sections with indented key-value rows.
    Lists of scalars render inline as comma-separated values. Fields annotated
    with :class:`~hassette.types.types.CliFormat` are formatted via the
    ``CLI_FORMATTERS`` registry in human mode.
    """
    if json_mode:
        sys.stdout.write(item.model_dump_json(indent=2) + "\n")
        sys.stdout.flush()
        return

    display_title = _humanize_model_name(type(item).__name__)
    data = item.model_dump(mode="json")
    field_formatters = _resolve_cli_formatters(type(item))
    _render_detail_panel(data, display_title, field_formatters)


def render_detail_dict(data: dict[str, Any], title: str, json_mode: bool) -> None:
    """Render a plain dict as a key-value panel or JSON object.

    Nested dicts render as labeled sections with indented key-value rows.
    Lists of scalars render inline as comma-separated values.  The caller
    passes the human-readable title directly (no class-name transformation).

    Args:
        data: The values dict to render.
        title: Panel title shown in human mode.
        json_mode: When ``True``, serialize ``data`` as JSON on stdout.
    """
    if json_mode:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        sys.stdout.flush()
        return

    _render_detail_panel(data, title)


def _render_detail_panel(
    data: dict[str, Any],
    title: str,
    field_formatters: dict[str, Callable[[Any], str]] | None = None,
) -> None:
    """Render a values dict as a key-value Rich panel (shared human-mode body).

    Nested non-empty dicts render as labeled sections with indented key-value rows;
    empty dicts are skipped so no orphaned section header appears. When sections
    exist, scalar fields are indented under a "General" header. Fields whose key is
    in ``field_formatters`` are formatted via that callable in place of the default.
    """
    formatters = field_formatters or {}

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="bold", no_wrap=True)
    table.add_column("value")

    has_sections = any(isinstance(v, dict) and v for v in data.values())
    general_header_emitted = False

    for key, value in data.items():
        if isinstance(value, dict):
            if not value:
                continue
            table.add_row("", "")
            table.add_row(f"[bold cyan]{_humanize_key(key)}[/bold cyan]", "")
            for sub_key, sub_value in value.items():
                table.add_row(f"  {sub_key}", _format_detail_value(sub_value))
        else:
            if has_sections and not general_header_emitted:
                table.add_row("[bold cyan]General[/bold cyan]", "")
                general_header_emitted = True
            if key in formatters and value is not None:
                formatted = formatters[key](value)
            else:
                formatted = _format_detail_value(value)
            table.add_row(f"  {key}" if has_sections else key, formatted)

    panel = Panel(table, title=title, expand=False)
    stdout_console.print(panel)


def render_raw(
    data: dict[str, Any] | list[Any],
    json_mode: bool,
) -> None:
    """Render an untyped dict or list as JSON or tree."""
    if json_mode:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        sys.stdout.flush()
        return

    stdout_console.print(JSON(json.dumps(data, indent=2)))


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
            no_wrap=col.max_width is None,
        )
    return table


def _humanize_model_name(name: str) -> str:
    """Convert a model class name to a human-readable title.

    ``'ConfigSchemaResponse'`` → ``'Config Schema'``, ``'SystemStatusResponse'`` → ``'System Status'``.
    """
    name = name.removesuffix("Response")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def _humanize_key(key: str) -> str:
    """Convert a snake_case field name to a title-cased section header."""
    return key.replace("_", " ").title()


def _format_detail_value(value: Any) -> str:
    """Format a value for the key-value detail panel."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return _format_list_inline(value)
    if isinstance(value, dict):
        return json.dumps(value, indent=2)
    return str(value)


def _format_list_inline(items: list[Any]) -> str:
    """Format a list for inline display in a detail panel."""
    if not items:
        return "—"
    if all(isinstance(v, (str, int, float, bool)) for v in items):
        return ", ".join(_scalar_str(v) for v in items)
    return f"{len(items)} items"


def _scalar_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _resolve_cli_formatters(model_cls: type[BaseModel]) -> dict[str, Callable[[Any], str]]:
    """Build a field-name → formatter mapping from CliFormat annotations on a model."""
    result: dict[str, Callable[[Any], str]] = {}
    for name, field_info in model_cls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, CliFormat) and meta.style in CLI_FORMATTERS:
                result[name] = CLI_FORMATTERS[meta.style]
                break
    return result

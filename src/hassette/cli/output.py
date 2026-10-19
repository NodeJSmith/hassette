"""Rendering layer for hassette CLI commands.

Commands return Pydantic models (or lists of models). This module handles all
output rendering: Rich tables for collections, key-value panels for single
objects, and JSON serialization for structured output. Value formatters
(durations, relative times) live in :mod:`hassette.cli.formatters`.

**stdout cleanliness contract**: In JSON mode, stdout contains exactly one
valid JSON document. All diagnostics, warnings, and "no results" messages go
to the stderr console. The stdout console is used only by render functions.
"""

import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from hassette_wire import AppGridResponse, CliFormat, requested_activity_parts
from pydantic import BaseModel
from rich.console import Console, OverflowMethod
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from hassette.cli.formatters import (
    EMPTY_VALUE,
    fmt_duration_ms,
    fmt_duration_s,
    fmt_instance_count,
    fmt_relative_time,
    fmt_services,
    fmt_uptime,
)

#: Width used for stdout when it isn't a terminal and ``$COLUMNS`` is unset. Rich's own non-TTY
#: default is 80 columns, which ellipsizes table cells in piped output (``hassette app | grep``
#: can't match a truncated name). Tables and panels don't expand to fill the console, so a wide
#: fallback only stops truncation; it doesn't pad short output.
PIPE_FALLBACK_WIDTH = 1000

JSON_INDENT = 2
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
CLI_FORMATTERS: dict[str, Callable[[Any], str]] = {
    "duration_ms": fmt_duration_ms,
    "duration_s": fmt_duration_s,
    "uptime": fmt_uptime,
    "relative_time": fmt_relative_time,
    "services": fmt_services,
    "instance_count": fmt_instance_count,
}

#: Rich style for each status-like cell value, keyed by lowercase text. See :func:`status_style`.
STATUS_STYLES: dict[str, str] = {
    **dict.fromkeys(("running", "success", "ok", "excellent", "good"), "green"),
    **dict.fromkeys(("failed", "error", "critical", "bad", "err"), "red"),
    **dict.fromkeys(("warning", "warn", "degraded", "timed_out"), "yellow"),
    **dict.fromkeys(("stopped", "disabled", "cancelled", "starting"), "dim"),
}


def make_stdout_console() -> Console:
    """Build the stdout console, widening Rich's 80-column default when piped.

    A terminal keeps its detected width, and an explicit ``$COLUMNS`` always wins (Rich reads it
    itself); only a non-TTY stdout with no ``$COLUMNS`` gets :data:`PIPE_FALLBACK_WIDTH`.

    The fallback sets width and height together: Rich only honors an assigned width ahead of its
    fixed 80x25 ``TERM=dumb`` size when both dimensions are set, and ``TERM=dumb`` with
    ``FORCE_COLOR`` is a common CI combination.
    """
    console = Console(file=sys.stdout, highlight=False)
    has_explicit_columns = os.environ.get("COLUMNS", "").isdigit()
    if not writes_to_tty(console) and not has_explicit_columns:
        console.size = (PIPE_FALLBACK_WIDTH, console.height)
    return console


def writes_to_tty(console: Console) -> bool:
    """Return whether ``console`` writes to a physical TTY.

    Deliberately not ``Console.is_terminal``: ``FORCE_COLOR`` or ``TTY_COMPATIBLE=1`` (common in CI)
    make that report ``True`` on a pipe, which would truncate piped tables. Those variables are
    about color and escape-code support, not about whether a human is reading a sized terminal.

    A closed stream counts as not a TTY: this runs at import time (via :func:`make_stdout_console`),
    and ``isatty()`` on a closed file raises ``ValueError``, which Rich's own check also absorbs.
    """
    try:
        return console.file.isatty()
    except ValueError:
        return False


stdout_console = make_stdout_console()
stderr_console = Console(file=sys.stderr, stderr=True, highlight=False)


@dataclass(frozen=True)
class Column:
    """Maps a model field to a table column for human-mode rendering.

    Args:
        field: Model field name. Supports dot notation for nested fields
            (e.g., ``"app.status"``). Nested access is done via ``getattr`` chains.
        header: Display header text shown in the table.
        max_width: Optional maximum column width in characters (human mode only).
            Ignored when the output is not a TTY (pipe mode).
        overflow: Rich overflow mode for cells exceeding ``max_width``.
            Defaults to ``"ellipsis"``.
        formatter: Optional callable that transforms the raw field value into a
            display string. Applied only in human mode; JSON mode uses raw values.
        style: Optional callable that receives the raw field value and returns a Rich
            style name (or ``None`` for no style). Applied only in human mode; Rich drops
            the style on non-terminal output, so piped tables stay plain text.
            :func:`status_style` covers status-like values.
    """

    field: str
    header: str
    max_width: int | None = None
    overflow: OverflowMethod = "ellipsis"
    formatter: Callable[[Any], str] | None = dc_field(default=None, compare=False, hash=False)
    style: Callable[[Any], str | None] | None = dc_field(default=None, compare=False, hash=False)
    row_formatter: Callable[[Any], str] | None = dc_field(default=None, compare=False, hash=False)
    """Optional callable that receives the whole row item (not just ``field``'s extracted
    value) and returns the display string. Takes precedence over both ``formatter`` and any
    ``CliFormat`` model-field fallback. Use when a cell's text depends on more than one field
    (e.g. a nullable timestamp whose placeholder text varies by a sibling status field)."""


def status_style(value: Any) -> str | None:
    """Return the Rich style for a status-like value, or ``None`` when it isn't a known status.

    Matches ``str(value)`` case-insensitively against :data:`STATUS_STYLES`.
    """
    return STATUS_STYLES.get(str(value).lower())


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


def _cell_text(value: Any, col: Column, fallback_meta: CliFormat | None = None) -> str:
    """Convert a raw field value to a table cell string (blank for None).

    Tables use empty string for missing values so cells stay visually clean.
    Detail panels use ``_format_detail_value`` which shows "—" instead.

    When ``col.formatter`` is unset, ``fallback_meta`` — a :class:`CliFormat` resolved
    from the model field's annotation metadata — is used instead. An explicit
    ``Column.formatter`` always takes precedence over model metadata.
    """
    if col.formatter is not None:
        try:
            return col.formatter(value)
        except (TypeError, ValueError):
            return str(value) if value is not None else ""
    if fallback_meta is not None:
        try:
            return _apply_cli_format(value, fallback_meta, none_default="")
        except (TypeError, ValueError):
            return str(value) if value is not None else ""
    if value is None:
        return ""
    return str(value)


def _table_cell(item: Any, col: Column, fallback_meta: CliFormat | None) -> str | Text:
    """Build one table cell for ``item``, wrapped in a styled :class:`Text` when ``col.style`` picks a style.

    A styled cell is a ``Text`` so its content is never parsed as Rich markup.
    """
    value = _extract_field(item, col.field)
    text = col.row_formatter(item) if col.row_formatter is not None else _cell_text(value, col, fallback_meta)
    style = col.style(value) if col.style is not None else None
    if style is None:
        return text
    return Text(text, style=style)


def render_table(
    items: Sequence[BaseModel],
    columns: list[Column],
    json_mode: bool,
) -> None:
    """Render a list of Pydantic models as a table or JSON array.

    Columns without an explicit ``formatter`` fall back to the :class:`CliFormat`
    metadata annotated on the matching model field, if any (see
    :func:`_resolve_cli_format_meta`). An explicit ``Column.formatter`` always
    takes precedence over model metadata.

    Args:
        items: Pydantic models to render.
        columns: Column definitions for human-mode table output.
        json_mode: When ``True``, serialize to JSON on stdout. When ``False``,
            render a Rich table on stdout.
    """
    if json_mode:
        data = [item.model_dump(mode="json") for item in items]
        _write_json(json.dumps(data, indent=JSON_INDENT))
        return

    if not items:
        stderr_console.print("No results.", highlight=False)
        return

    table = _build_table(columns, is_tty=writes_to_tty(stdout_console))
    fallback_meta = _resolve_cli_format_meta(type(items[0]))
    for item in items:
        table.add_row(*(_table_cell(item, col, fallback_meta.get(col.field)) for col in columns))

    stdout_console.print(table)


def warn_missing_activity(grid: AppGridResponse) -> None:
    """Print a one-line stderr warning naming the ``activity`` parts the server couldn't compute.

    A part is ``None`` when its enrichment failed, or when it didn't run: ``activity_buckets`` and
    ``last_error`` only run for a window, so they are named only when the response's ``since`` echo
    says the request had one. Goes to stderr in both modes, so table and JSON output on stdout stay
    clean. No-op for an empty grid or when every requested part is present.
    """
    windowed = grid.since is not None  # the echo of the request's since: what the server actually computed
    missing = [
        part
        for part in requested_activity_parts(windowed=windowed)
        if any(getattr(row.activity, part) is None for row in grid.apps)
    ]
    if missing:
        stderr_console.print(
            f"[yellow]Warning:[/yellow] partial data, the server could not compute: {escape(', '.join(missing))}",
            highlight=False,
        )


def render_detail(
    item: BaseModel,
    json_mode: bool,
) -> None:
    """Render a single Pydantic model as a key-value panel or JSON object.

    Nested sub-models render as labeled sections with indented key-value rows.
    Lists of scalars render inline as comma-separated values. Fields annotated
    with :class:`~hassette_wire.CliFormat` are formatted via the
    ``CLI_FORMATTERS`` registry in human mode.
    """
    if json_mode:
        _write_json(item.model_dump_json(indent=JSON_INDENT))
        return

    display_title = _humanize_model_name(type(item).__name__)
    data = item.model_dump(mode="json")
    field_meta = _resolve_cli_format_meta(type(item))
    _render_detail_panel(data, display_title, field_meta)


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
        _write_json(json.dumps(data, indent=JSON_INDENT))
        return

    _render_detail_panel(data, title)


def _write_json(document: str) -> None:
    """Write one serialized JSON document to stdout, newline-terminated, and flush."""
    sys.stdout.write(document + "\n")
    sys.stdout.flush()


def _render_detail_panel(
    data: dict[str, Any],
    title: str,
    field_meta: dict[str, CliFormat] | None = None,
) -> None:
    """Render a values dict as a key-value Rich panel (shared human-mode body).

    Nested non-empty dicts render as labeled sections with indented key-value rows;
    empty dicts are skipped so no orphaned section header appears. When sections
    exist, scalar fields are indented under a "General" header. Fields whose key is
    in ``field_meta`` are formatted via the matching :class:`CliFormat` in place of
    the default.
    """
    meta_map = field_meta or {}

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
            meta = meta_map.get(key)
            if meta is not None:
                formatted = _apply_cli_format(value, meta, none_default=_format_detail_value(None))
            else:
                formatted = _format_detail_value(value)
            table.add_row(f"  {key}" if has_sections else key, formatted)

    panel = Panel(table, title=title, expand=False)
    stdout_console.print(panel)


def _build_table(columns: list[Column], is_tty: bool) -> Table:
    """Build a Rich Table from column definitions.

    In non-TTY (pipe) mode, ``max_width`` is ignored so piped output
    contains full values without truncation.
    """
    table = Table(show_header=True, header_style="bold")
    for col in columns:
        effective_max_width = col.max_width if is_tty else None
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
    return CAMEL_BOUNDARY_RE.sub(" ", name)


def _humanize_key(key: str) -> str:
    """Convert a snake_case field name to a title-cased section header."""
    return key.replace("_", " ").title()


def _format_detail_value(value: Any) -> str:
    """Format a value for the key-value detail panel."""
    if value is None:
        return EMPTY_VALUE
    if isinstance(value, bool):
        return _format_bool(value)
    if isinstance(value, list):
        return _format_list_inline(value)
    if isinstance(value, dict):
        return json.dumps(value, indent=JSON_INDENT)
    return str(value)


def _format_list_inline(items: list[Any]) -> str:
    """Format a list for inline display in a detail panel."""
    if not items:
        return EMPTY_VALUE
    if all(isinstance(v, (str, int, float, bool)) for v in items):
        return ", ".join(_scalar_str(v) for v in items)
    return f"{len(items)} items"


def _scalar_str(value: Any) -> str:
    if isinstance(value, bool):
        return _format_bool(value)
    return str(value)


def _format_bool(value: bool) -> str:
    """Render a bool as lowercase JSON-style text."""
    return "true" if value else "false"


def _resolve_cli_format_meta(model_cls: type[BaseModel]) -> dict[str, CliFormat]:
    """Build a field-name → CliFormat mapping from annotations on a model's fields."""
    result: dict[str, CliFormat] = {}
    for name, field_info in model_cls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, CliFormat) and meta.style in CLI_FORMATTERS:
                result[name] = meta
                break
    return result


def _apply_cli_format(value: Any, meta: CliFormat, none_default: str) -> str:
    """Apply a CliFormat's style formatter, using ``meta.none_text`` (or ``none_default``) for None."""
    if value is None:
        return meta.none_text if meta.none_text is not None else none_default
    return CLI_FORMATTERS[meta.style](value)

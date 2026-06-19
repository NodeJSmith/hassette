"""Unit tests for the CLI rendering layer (hassette.cli.output)."""

import json
import time
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from rich.console import Console
from whenever import Instant

import hassette.cli.output as output_module
from hassette.cli.output import (
    Column,
    _build_table,
    _cell_text,
    _extract_field,
    fmt_duration_ms,
    fmt_duration_s,
    fmt_relative_time,
    render_detail,
    render_raw,
    render_table,
)
from tests.unit.cli.conftest import capture_human

# Simple test models


class SimpleItem(BaseModel):
    name: str
    count: int
    active: bool = True
    note: str | None = None


class NestedItem(BaseModel):
    id: int
    inner: dict[str, Any]


class SubModel(BaseModel):
    host: str
    port: int
    enabled: bool = True


class ParentModel(BaseModel):
    name: str
    debug: bool = False
    tags: list[str] = []
    sub: SubModel = SubModel(host="localhost", port=8080)


# Column definition


class TestColumn:
    def test_required_fields(self) -> None:
        col = Column(field="name", header="Name")
        assert col.field == "name"
        assert col.header == "Name"

    def test_default_max_width_none(self) -> None:
        col = Column(field="name", header="Name")
        assert col.max_width is None

    def test_default_overflow_ellipsis(self) -> None:
        col = Column(field="name", header="Name")
        assert col.overflow == "ellipsis"

    def test_default_formatter_none(self) -> None:
        col = Column(field="name", header="Name")
        assert col.formatter is None

    def test_with_formatter(self) -> None:
        col = Column(field="ts", header="Time", formatter=fmt_relative_time)
        assert col.formatter is fmt_relative_time

    def test_with_max_width(self) -> None:
        col = Column(field="msg", header="Message", max_width=40)
        assert col.max_width == 40

    def test_frozen(self) -> None:
        col = Column(field="name", header="Name")
        with pytest.raises((AttributeError, TypeError)):
            col.field = "other"  # pyright: ignore[reportAttributeAccessIssue]


# _extract_field


class TestExtractField:
    def test_simple_field(self) -> None:
        item = SimpleItem(name="alpha", count=1)
        assert _extract_field(item, "name") == "alpha"
        assert _extract_field(item, "count") == 1

    def test_missing_field_returns_none(self) -> None:
        item = SimpleItem(name="alpha", count=1)
        assert _extract_field(item, "nonexistent") is None

    def test_none_value_field(self) -> None:
        item = SimpleItem(name="alpha", count=1, note=None)
        assert _extract_field(item, "note") is None

    def test_dict_field_access(self) -> None:
        data = {"key": "value", "num": 42}
        assert _extract_field(data, "key") == "value"
        assert _extract_field(data, "num") == 42

    def test_dict_missing_key_returns_none(self) -> None:
        data = {"key": "value"}
        assert _extract_field(data, "missing") is None

    def test_dot_notation_nested(self) -> None:
        item = NestedItem(id=1, inner={"label": "test"})
        assert _extract_field(item, "inner.label") == "test"

    def test_dot_notation_none_segment(self) -> None:
        item = SimpleItem(name="alpha", count=1, note=None)
        # note is None, trying to go deeper returns None
        assert _extract_field(item, "note.sub") is None


# Built-in formatters


class TestFmtRelativeTime:
    def test_recent_epoch(self) -> None:
        now = time.time()
        result = fmt_relative_time(now - 30)
        assert "s ago" in result or result == "just now"

    def test_minutes_ago(self) -> None:
        result = fmt_relative_time(time.time() - 120)
        assert "m ago" in result

    def test_hours_ago(self) -> None:
        result = fmt_relative_time(time.time() - 7200)
        assert "h ago" in result

    def test_days_ago(self) -> None:
        result = fmt_relative_time(time.time() - 90000)
        assert "d ago" in result

    def test_just_now(self) -> None:
        result = fmt_relative_time(time.time())
        assert result == "just now"

    def test_none_returns_empty(self) -> None:
        assert fmt_relative_time(None) == ""

    def test_invalid_value_returns_string(self) -> None:
        result = fmt_relative_time("not-a-timestamp")
        assert isinstance(result, str)

    def test_iso_string(self) -> None:
        epoch_2h_ago = time.time() - 7200
        past_iso = Instant.from_timestamp(epoch_2h_ago).format_iso()
        result = fmt_relative_time(past_iso)
        assert "h ago" in result


class TestFmtDurationMs:
    def test_none_returns_empty(self) -> None:
        assert fmt_duration_ms(None) == ""

    def test_small_ms_shows_ms(self) -> None:
        assert fmt_duration_ms(25) == "25ms"

    def test_subsecond_ms_shows_ms(self) -> None:
        assert fmt_duration_ms(450) == "450ms"

    def test_large_ms_shows_seconds(self) -> None:
        assert fmt_duration_ms(12000) == "12.0s"

    def test_invalid_value_returns_string(self) -> None:
        assert fmt_duration_ms("invalid") == "invalid"


class TestFmtDurationS:
    def test_none_returns_empty(self) -> None:
        assert fmt_duration_s(None) == ""

    def test_subsecond_shows_ms(self) -> None:
        result = fmt_duration_s(0.45)
        assert "ms" in result

    def test_seconds_shows_s(self) -> None:
        result = fmt_duration_s(1.5)
        assert result == "1.5s"

    def test_invalid_value_returns_string(self) -> None:
        assert fmt_duration_s("invalid") == "invalid"


# _cell_text


class TestCellText:
    def test_no_formatter_returns_str(self) -> None:
        col = Column(field="name", header="Name")
        assert _cell_text("hello", col) == "hello"

    def test_none_without_formatter_returns_empty(self) -> None:
        col = Column(field="name", header="Name")
        assert _cell_text(None, col) == ""

    def test_formatter_applied(self) -> None:
        col = Column(field="count", header="Count", formatter=lambda v: f"#{v}")
        assert _cell_text(42, col) == "#42"

    def test_formatter_applied_in_pipe_mode(self) -> None:
        # Formatters are always applied; TTY mode only affects max_width at table level
        col = Column(field="ts", header="Time", formatter=lambda _: "relative")
        result = _cell_text(12345, col)
        assert result == "relative"

    def test_formatter_exception_falls_back_to_str(self) -> None:
        def bad_formatter(_v: Any) -> str:
            raise ValueError("oops")

        col = Column(field="val", header="Val", formatter=bad_formatter)
        result = _cell_text("raw", col)
        assert result == "raw"


# render_table — JSON mode


class TestRenderTableJsonMode:
    def test_valid_json_on_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        items = [SimpleItem(name="a", count=1), SimpleItem(name="b", count=2)]
        columns = [Column("name", "Name"), Column("count", "Count")]
        render_table(items, columns, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_json_contains_all_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        items = [SimpleItem(name="alpha", count=10, active=True, note="hi")]
        columns = [Column("name", "Name")]
        render_table(items, columns, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        # JSON uses the full model dump, not just column fields
        assert parsed[0]["name"] == "alpha"
        assert parsed[0]["count"] == 10
        assert parsed[0]["note"] == "hi"

    def test_empty_list_json_outputs_empty_array(self, capsys: pytest.CaptureFixture[str]) -> None:
        columns = [Column("name", "Name")]
        render_table([], columns, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == []

    def test_json_mode_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        items = [SimpleItem(name="a", count=1)]
        columns = [Column("name", "Name")]
        render_table(items, columns, json_mode=True)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_empty_list_json_mode_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        columns = [Column("name", "Name")]
        render_table([], columns, json_mode=True)
        captured = capsys.readouterr()
        # stdout has "[]", stderr is empty
        assert captured.err == ""
        assert json.loads(captured.out) == []

    def test_json_output_is_parseable(self, capsys: pytest.CaptureFixture[str]) -> None:
        items = [SimpleItem(name="x", count=99)]
        columns = [Column("name", "Name"), Column("count", "Count")]
        render_table(items, columns, json_mode=True)
        captured = capsys.readouterr()
        # Must be valid JSON — no ANSI codes, no Rich markup
        parsed = json.loads(captured.out)
        assert parsed[0]["name"] == "x"


# render_table — human mode


class TestRenderTableHumanMode:
    def test_empty_list_prints_no_results_to_stderr(self) -> None:
        columns = [Column("name", "Name")]
        _stdout, stderr = capture_human(render_table, [], columns, json_mode=False)
        assert "No results" in stderr

    def test_empty_list_human_mode_nothing_on_stdout(self) -> None:
        columns = [Column("name", "Name")]
        stdout, _stderr = capture_human(render_table, [], columns, json_mode=False)
        assert stdout == ""

    def test_table_with_items_goes_to_stdout(self) -> None:
        items = [SimpleItem(name="alpha", count=1)]
        columns = [Column("name", "Name"), Column("count", "Count")]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert len(stdout) > 0

    def test_table_contains_field_values(self) -> None:
        items = [SimpleItem(name="alpha", count=42)]
        columns = [Column("name", "Name"), Column("count", "Count")]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert "alpha" in stdout
        assert "42" in stdout

    def test_table_contains_headers(self) -> None:
        items = [SimpleItem(name="x", count=1)]
        columns = [Column("name", "Name"), Column("count", "Items")]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert "Name" in stdout
        assert "Items" in stdout

    def test_formatter_applied_in_human_mode(self) -> None:
        items = [SimpleItem(name="hello", count=5)]
        columns = [Column("name", "Name", formatter=lambda v: v.upper())]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert "HELLO" in stdout

    def test_none_field_renders_empty(self) -> None:
        items = [SimpleItem(name="x", count=1, note=None)]
        columns = [Column("name", "Name"), Column("note", "Note")]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert "x" in stdout

    def test_multiple_items_all_appear(self) -> None:
        items = [
            SimpleItem(name="alpha", count=1),
            SimpleItem(name="beta", count=2),
            SimpleItem(name="gamma", count=3),
        ]
        columns = [Column("name", "Name")]
        stdout, _stderr = capture_human(render_table, items, columns, json_mode=False)
        assert "alpha" in stdout
        assert "beta" in stdout
        assert "gamma" in stdout


# render_table — pipe detection


class TestRenderTablePipeDetection:
    def test_pipe_mode_disables_max_width(self) -> None:
        """In non-TTY mode, columns should not be created with max_width."""
        columns = [Column("name", "Name", max_width=10)]
        table = _build_table(columns, is_terminal=False)
        # Verify first column has no max_width (None)
        col_obj = table.columns[0]
        assert col_obj.max_width is None

    def test_terminal_mode_uses_max_width(self) -> None:
        """In TTY mode, columns should respect max_width."""
        columns = [Column("name", "Name", max_width=10)]
        table = _build_table(columns, is_terminal=True)
        col_obj = table.columns[0]
        assert col_obj.max_width == 10

    def test_pipe_mode_shows_full_values(self) -> None:
        """Non-TTY output should not truncate values (max_width ignored)."""
        long_name = "a" * 100
        items = [SimpleItem(name=long_name, count=1)]
        columns = [Column("name", "Name", max_width=20)]

        stdout_buf = StringIO()
        # Simulate non-TTY: is_terminal=False, large width so content isn't wrapped
        new_stdout_console = Console(file=stdout_buf, highlight=False, no_color=True, width=200)
        new_stderr_console = Console(file=StringIO(), highlight=False, no_color=True)
        with (
            patch.object(output_module, "stdout_console", new_stdout_console),
            patch.object(output_module, "stderr_console", new_stderr_console),
        ):
            render_table(items, columns, json_mode=False)

        output = stdout_buf.getvalue()
        assert long_name in output


# render_detail — JSON mode


class TestRenderDetailJsonMode:
    def test_valid_json_on_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = SimpleItem(name="test", count=7, active=True)
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["name"] == "test"
        assert parsed["count"] == 7

    def test_json_mode_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = SimpleItem(name="test", count=7)
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_json_contains_all_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = SimpleItem(name="alpha", count=10, active=False, note="hi")
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["name"] == "alpha"
        assert parsed["count"] == 10
        assert parsed["active"] is False
        assert parsed["note"] == "hi"

    def test_json_is_indented(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = SimpleItem(name="test", count=1)
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        # model_dump_json with indent=2 produces multi-line output
        assert "\n" in captured.out


# render_detail — human mode


class TestRenderDetailHumanMode:
    def test_output_on_stdout(self) -> None:
        item = SimpleItem(name="hello", count=5)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert len(stdout) > 0

    def test_field_names_appear(self) -> None:
        item = SimpleItem(name="hello", count=5)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "name" in stdout
        assert "count" in stdout

    def test_values_appear(self) -> None:
        item = SimpleItem(name="hello", count=5)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "hello" in stdout
        assert "5" in stdout

    def test_nothing_on_stderr(self) -> None:
        item = SimpleItem(name="hello", count=5)
        _stdout, stderr = capture_human(render_detail, item, json_mode=False)
        assert stderr == ""

    def test_humanized_panel_title(self) -> None:
        item = SimpleItem(name="x", count=1)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "Simple Item" in stdout

    def test_boolean_renders_lowercase(self) -> None:
        item = SimpleItem(name="x", count=1, active=True)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "true" in stdout

    def test_none_renders_em_dash(self) -> None:
        item = SimpleItem(name="x", count=1, note=None)
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "—" in stdout

    def test_nested_dict_renders_as_section(self) -> None:
        item = ParentModel(name="test", sub=SubModel(host="0.0.0.0", port=9000))
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "Sub" in stdout
        assert "host" in stdout
        assert "0.0.0.0" in stdout
        assert "port" in stdout
        assert "9000" in stdout

    def test_nested_section_keys_are_indented(self) -> None:
        item = ParentModel(name="test")
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        for line in stdout.splitlines():
            if "host" in line and "localhost" in line:
                assert line.startswith(" ") or "  " in line
                break
        else:
            pytest.fail("Expected indented host row in section")

    def test_list_of_scalars_renders_inline(self) -> None:
        item = ParentModel(name="test", tags=["alpha", "beta", "gamma"])
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "alpha" in stdout
        assert "beta" in stdout
        assert "gamma" in stdout

    def test_empty_list_renders_em_dash(self) -> None:
        item = ParentModel(name="test", tags=[])
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "—" in stdout


# render_raw — JSON mode


class TestRenderRawJsonMode:
    def test_dict_serialized_to_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        data = {"light": {"turn_on": {"description": "Turn on light"}}}
        render_raw(data, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == data

    def test_list_serialized_to_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        data = [{"name": "a"}, {"name": "b"}]
        render_raw(data, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == data

    def test_nothing_on_stderr_json_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_raw({"key": "val"}, json_mode=True)
        captured = capsys.readouterr()
        assert captured.err == ""


# render_raw — human mode


class TestRenderRawHumanMode:
    def test_dict_output_on_stdout(self) -> None:
        data = {"key": "value"}
        stdout, _stderr = capture_human(render_raw, data, json_mode=False)
        assert len(stdout) > 0

    def test_dict_content_visible(self) -> None:
        data = {"service": "light.turn_on"}
        stdout, _stderr = capture_human(render_raw, data, json_mode=False)
        assert "service" in stdout
        assert "light.turn_on" in stdout


# stdout cleanliness contract


class TestStdoutCleanliness:
    def test_json_table_stdout_is_valid_json_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Stdout in JSON mode must be exactly one valid JSON document."""
        items = [SimpleItem(name="x", count=1), SimpleItem(name="y", count=2)]
        columns = [Column("name", "Name")]
        render_table(items, columns, json_mode=True)
        captured = capsys.readouterr()
        # Strip trailing newline and parse — must succeed without error
        parsed = json.loads(captured.out.strip())
        assert isinstance(parsed, list)

    def test_json_detail_stdout_is_valid_json_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Stdout in JSON mode for detail must be exactly one valid JSON document."""
        item = SimpleItem(name="hello", count=3)
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert isinstance(parsed, dict)

    def test_json_raw_stdout_is_valid_json_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Stdout in JSON mode for raw must be exactly one valid JSON document."""
        data = {"a": 1, "b": 2}
        render_raw(data, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out.strip())
        assert parsed == data

    def test_human_table_nothing_on_stderr_for_non_empty(self) -> None:
        """For non-empty tables, no diagnostics on stderr."""
        items = [SimpleItem(name="a", count=1)]
        columns = [Column("name", "Name")]
        _stdout, stderr = capture_human(render_table, items, columns, json_mode=False)
        assert stderr == ""


# Architectural constraint verification


class TestArchitecturalConstraint:
    def test_render_functions_exist(self) -> None:
        """Adding a new format would require changes only in output.py.

        Verify the three render functions exist and are the rendering interface.
        """
        assert callable(render_table)
        assert callable(render_detail)
        assert callable(render_raw)

    def test_column_dataclass_is_public_interface(self) -> None:
        """Column is the public column definition type for commands."""
        col = Column(field="f", header="H")
        assert col.field == "f"
        assert col.header == "H"

    def test_builtin_formatters_are_public(self) -> None:
        """Built-in formatters are publicly accessible for commands to reference."""
        assert callable(fmt_relative_time)
        assert callable(fmt_duration_ms)
        assert callable(fmt_duration_s)

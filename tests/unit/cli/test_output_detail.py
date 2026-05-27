"""Tests for CLI detail rendering: helpers, formatters, and CliFormat integration."""

import json
from typing import Annotated

import pytest
from pydantic import BaseModel

from hassette.cli.output import (
    _format_detail_value,
    _format_list_inline,
    _humanize_key,
    _humanize_model_name,
    _resolve_cli_formatters,
    fmt_handler_short,
    fmt_next_run,
    fmt_uptime,
    render_detail,
)
from hassette.types.types import CliFormat
from tests.unit.cli.conftest import capture_human


class SimpleItem(BaseModel):
    name: str
    count: int
    active: bool = True
    note: str | None = None


class AnnotatedModel(BaseModel):
    name: str
    uptime_seconds: Annotated[float, CliFormat("uptime")]
    avg_duration: Annotated[float, CliFormat("duration_ms")]
    last_seen: Annotated[float | None, CliFormat("relative_time")]
    plain_float: float = 1.5


class TestHumanizeModelName:
    def test_strips_response_suffix(self) -> None:
        assert _humanize_model_name("ConfigResponse") == "Config"

    def test_camel_case_to_spaced(self) -> None:
        assert _humanize_model_name("SystemStatusResponse") == "System Status"

    def test_no_response_suffix(self) -> None:
        assert _humanize_model_name("SimpleItem") == "Simple Item"

    def test_single_word(self) -> None:
        assert _humanize_model_name("Config") == "Config"

    def test_multi_word_no_suffix(self) -> None:
        assert _humanize_model_name("AppHealth") == "App Health"


class TestHumanizeKey:
    def test_snake_case_to_title(self) -> None:
        assert _humanize_key("file_watcher") == "File Watcher"

    def test_single_word(self) -> None:
        assert _humanize_key("logging") == "Logging"

    def test_multi_word(self) -> None:
        assert _humanize_key("web_api") == "Web Api"


class TestFormatDetailValue:
    def test_none_returns_em_dash(self) -> None:
        assert _format_detail_value(None) == "—"

    def test_true_lowercase(self) -> None:
        assert _format_detail_value(True) == "true"

    def test_false_lowercase(self) -> None:
        assert _format_detail_value(False) == "false"

    def test_string_passthrough(self) -> None:
        assert _format_detail_value("hello") == "hello"

    def test_int_passthrough(self) -> None:
        assert _format_detail_value(42) == "42"

    def test_float_passthrough(self) -> None:
        assert _format_detail_value(3.14) == "3.14"

    def test_dict_returns_json(self) -> None:
        result = _format_detail_value({"key": "val"})
        parsed = json.loads(result)
        assert parsed == {"key": "val"}

    def test_empty_list_returns_em_dash(self) -> None:
        assert _format_detail_value([]) == "—"

    def test_scalar_list_comma_separated(self) -> None:
        result = _format_detail_value(["a", "b", "c"])
        assert result == "a, b, c"

    def test_object_list_shows_count(self) -> None:
        result = _format_detail_value([{"name": "x"}, {"name": "y"}])
        assert result == "2 items"


class TestFormatListInline:
    def test_empty_list(self) -> None:
        assert _format_list_inline([]) == "—"

    def test_string_list(self) -> None:
        assert _format_list_inline(["a", "b"]) == "a, b"

    def test_int_list(self) -> None:
        assert _format_list_inline([1, 2, 3]) == "1, 2, 3"

    def test_bool_list_lowercase(self) -> None:
        result = _format_list_inline([True, False])
        assert result == "true, false"

    def test_mixed_scalar_list(self) -> None:
        result = _format_list_inline(["host", 8080, True])
        assert "host" in result
        assert "8080" in result
        assert "true" in result

    def test_dict_list_shows_count(self) -> None:
        assert _format_list_inline([{"a": 1}, {"b": 2}, {"c": 3}]) == "3 items"

    def test_single_item(self) -> None:
        assert _format_list_inline(["only"]) == "only"


class TestFmtUptime:
    def test_none_returns_empty(self) -> None:
        assert fmt_uptime(None) == ""

    def test_seconds_only(self) -> None:
        assert fmt_uptime(45) == "45s"

    def test_minutes_and_seconds(self) -> None:
        assert fmt_uptime(150) == "2m 30s"

    def test_hours_minutes_seconds(self) -> None:
        assert fmt_uptime(9005) == "2h 30m 5s"

    def test_invalid_value_returns_string(self) -> None:
        assert fmt_uptime("invalid") == "invalid"


class TestFmtNextRun:
    def test_none_returns_done(self) -> None:
        assert fmt_next_run(None) == "done"

    def test_delegates_to_relative_time(self) -> None:
        import time

        result = fmt_next_run(time.time() - 120)
        assert "ago" in result


class TestFmtHandlerShort:
    def test_extracts_method_name(self) -> None:
        assert fmt_handler_short("hautomate.meeting_app.MeetingApp.on_light_changed") == "on_light_changed"

    def test_none_returns_empty(self) -> None:
        assert fmt_handler_short(None) == ""

    def test_no_dots_returns_as_is(self) -> None:
        assert fmt_handler_short("simple") == "simple"


class TestResolveCliFormatters:
    def test_annotated_model_resolves_formatters(self) -> None:
        result = _resolve_cli_formatters(AnnotatedModel)
        assert "uptime_seconds" in result
        assert "avg_duration" in result
        assert "last_seen" in result

    def test_unannotated_fields_excluded(self) -> None:
        result = _resolve_cli_formatters(AnnotatedModel)
        assert "name" not in result
        assert "plain_float" not in result

    def test_model_without_annotations_returns_empty(self) -> None:
        result = _resolve_cli_formatters(SimpleItem)
        assert result == {}

    def test_resolved_formatters_are_callable(self) -> None:
        result = _resolve_cli_formatters(AnnotatedModel)
        assert result["uptime_seconds"](9005) == "2h 30m 5s"
        assert result["avg_duration"](450) == "450ms"


class TestRenderDetailCliFormat:
    def test_annotated_fields_are_formatted(self) -> None:
        item = AnnotatedModel(
            name="myapp",
            uptime_seconds=9005.0,
            avg_duration=450.0,
            last_seen=None,
            plain_float=3.14,
        )
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "2h 30m 5s" in stdout
        assert "450ms" in stdout

    def test_unannotated_float_not_formatted(self) -> None:
        item = AnnotatedModel(
            name="myapp",
            uptime_seconds=60.0,
            avg_duration=100.0,
            last_seen=None,
            plain_float=3.14,
        )
        stdout, _stderr = capture_human(render_detail, item, json_mode=False)
        assert "3.14" in stdout

    def test_json_mode_ignores_annotations(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = AnnotatedModel(
            name="myapp",
            uptime_seconds=9005.0,
            avg_duration=450.0,
            last_seen=None,
        )
        render_detail(item, json_mode=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["uptime_seconds"] == 9005.0
        assert parsed["avg_duration"] == 450.0

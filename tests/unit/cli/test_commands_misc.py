"""Unit tests for hassette config and event commands."""

import json
from typing import Any
from unittest.mock import patch

from hassette.cli.commands.misc import EVENT_COLUMNS, cmd_config, cmd_event
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import (
    make_config_response,
    make_event_entry,
)
from tests.unit.cli.conftest import CLIClientFactory, capture_stdout

# ---------------------------------------------------------------------------
# cmd_config
# ---------------------------------------------------------------------------


class TestCmdConfig:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """config command fetches from GET /api/config."""
        config_data = make_config_response()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_config()

        assert "/api/config" in called_paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """config command produces a key-value panel with key fields."""
        config_data = make_config_response()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_config()
        output = buf.getvalue()
        assert "dev_mode" in output
        assert "base_url" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """config --json outputs a complete JSON object."""
        config_data = make_config_response()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.misc.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_config(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert "web_api" in parsed
        assert parsed["web_api"]["port"] == 8126


# ---------------------------------------------------------------------------
# cmd_event
# ---------------------------------------------------------------------------


class TestCmdEvent:
    def _event_body(self, count: int = 2) -> list[dict[str, Any]]:
        return [make_event_entry(type=f"event_{i}", entity_id=f"light.room_{i}").model_dump() for i in range(count)]

    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """event command fetches from GET /api/events/recent."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/events/recent", 200, self._event_body())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_event()

        assert "/api/events/recent" in called_paths

    def test_limit_passed_as_query_param(self, cli_client_factory: CLIClientFactory) -> None:
        """event --limit 10 passes limit=10 as a query parameter."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/events/recent", 200, self._event_body())])
        captured_params: list[dict[str, Any] | None] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            captured_params.append(params)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_event(limit=10)

        assert len(captured_params) == 1
        assert captured_params[0] is not None
        assert captured_params[0]["limit"] == 10

    def test_no_limit_passes_no_params(self, cli_client_factory: CLIClientFactory) -> None:
        """event without --limit passes no query params."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/events/recent", 200, self._event_body())])
        captured_params: list[dict[str, Any] | None] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            captured_params.append(params)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_event()

        assert captured_params[0] == {}

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """event command renders a table with event type and entity columns."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/events/recent", 200, self._event_body())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_event()
        output = buf.getvalue()
        assert "event_0" in output
        assert "light.room_0" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """event --json outputs a JSON array of event entries."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/events/recent", 200, self._event_body())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.misc.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_event(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["type"] == "event_0"

    def test_event_columns_defined(self) -> None:
        """EVENT_COLUMNS includes the expected display fields."""
        field_names = [c.field for c in EVENT_COLUMNS]
        assert "type" in field_names
        assert "entity_id" in field_names
        assert "timestamp" in field_names

    def test_event_columns_fit_80_chars(self) -> None:
        """Sum of EVENT_COLUMNS max_widths stays within a reasonable 80-col budget.

        Rich adds borders and padding on top of max_width; the sum of max_widths
        itself should leave room for that overhead (~2 chars per col + 2 outer borders).
        """
        total = sum(c.max_width for c in EVENT_COLUMNS if c.max_width is not None)
        # 3 columns x 2 char overhead + 2 outer borders = 8 chars
        overhead = len(EVENT_COLUMNS) * 2 + 2
        assert total + overhead <= 80, f"Column widths ({total}) + overhead ({overhead}) exceed 80"

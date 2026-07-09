"""Unit tests for hassette config command."""

import json
from unittest.mock import patch

from hassette.cli.commands.misc import cmd_config
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import make_config_schema_response
from tests.unit.cli.conftest import CLIClientFactory, capture_stdout

# cmd_config


class TestCmdConfig:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """config command fetches from GET /api/config."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
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
        """config command produces a key-value panel showing config_values fields."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.misc.make_client", return_value=client),
        ):
            cmd_config()
        output = buf.getvalue()
        assert "dev_mode" in output
        assert "base_url" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """config --json outputs config_values as a JSON object."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.misc.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_config(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert "web_api" in parsed
        assert parsed["web_api"]["port"] == 8126

    def test_json_mode_renders_config_values_not_envelope(self, cli_client_factory: CLIClientFactory) -> None:
        """config --json outputs only config_values, not the full ConfigSchemaResponse envelope."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.misc.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_config(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        # Rendered dict is config_values, not the outer envelope
        assert "config_schema" not in parsed
        assert "config_values" not in parsed
        assert "dev_mode" in parsed

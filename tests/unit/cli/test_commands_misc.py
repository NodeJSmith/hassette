"""Unit tests for hassette config command."""

from hassette.cli.commands.misc import cmd_config
from hassette.test_utils.web_response_helpers import make_config_schema_response
from tests.unit.cli.conftest import CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.misc.make_client")

# cmd_config


class TestCmdConfig:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Config command fetches from GET /api/config."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        spy = runner.spy(client, cmd_config)

        assert "/api/config" in spy.paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """Config command produces a key-value panel showing config_values fields."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])
        output = runner.stdout(client, cmd_config)
        assert "dev_mode" in output
        assert "base_url" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """Config --json outputs config_values as a JSON object."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])

        parsed = runner.json_output(client, cmd_config)
        assert "web_api" in parsed
        assert parsed["web_api"]["port"] == 8126

    def test_json_mode_renders_config_values_not_envelope(self, cli_client_factory: CLIClientFactory) -> None:
        """Config --json outputs only config_values, not the full ConfigSchemaResponse envelope."""
        config_data = make_config_schema_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/config", 200, config_data.model_dump())])

        parsed = runner.json_output(client, cmd_config)
        # Rendered dict is config_values, not the outer envelope
        assert "config_schema" not in parsed
        assert "config_values" not in parsed
        assert "dev_mode" in parsed

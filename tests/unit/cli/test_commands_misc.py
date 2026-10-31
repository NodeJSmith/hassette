"""Unit tests for hassette config command."""

from hassette_wire import ConfigSchemaResponse

from hassette.cli.commands.misc import cmd_config
from tests.support.web_response_helpers import make_config_schema_response
from tests.unit.cli.conftest import CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.misc.make_client")


def line_with(output: str, text: str) -> str:
    """Return the first rendered line containing ``text``."""
    return next(line for line in output.splitlines() if text in line)


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


class TestCmdConfigDefaultMarkers:
    RESPONSE = ConfigSchemaResponse(
        config_schema={},
        config_values={
            "unchanged": 30,
            "overridden": 60,
            "unset_token": None,
            "no_default": None,
            "default_group": {"retries": 3},
            "partial_group": {"retries": 3, "host": "custom"},
            "extra_field_group": {"retries": 3, "origins": []},
        },
        config_defaults={
            "unchanged": 30,
            "overridden": 45,
            "unset_token": None,
            "default_group": {"retries": 3},
            "partial_group": {"retries": 3, "host": "localhost"},
            "extra_field_group": {"retries": 3},
        },
    )

    def human_output(self, cli_client_factory: CLIClientFactory) -> str:
        routes = [("GET", "/api/config", 200, self.RESPONSE.model_dump())]
        return runner.stdout(cli_client_factory.build_with_routes(routes), cmd_config)

    def test_marks_scalar_defaults_only(self, cli_client_factory: CLIClientFactory) -> None:
        """A scalar equal to its default is marked; an override keeps its bare value."""
        output = self.human_output(cli_client_factory)
        assert "30 (default)" in line_with(output, "unchanged")
        assert "(default)" in line_with(output, "unset_token")
        assert "60" in line_with(output, "overridden")
        assert "(default)" not in line_with(output, "overridden")

    def test_none_without_a_default_is_not_marked(self, cli_client_factory: CLIClientFactory) -> None:
        """A None value is only a default when the field actually declares one."""
        assert "(default)" not in line_with(self.human_output(cli_client_factory), "no_default")

    def test_group_marked_only_when_entirely_default(self, cli_client_factory: CLIClientFactory) -> None:
        """A section header is marked only when every field in the group equals its default."""
        output = self.human_output(cli_client_factory)
        assert "Default Group (default)" in line_with(output, "Default Group")
        assert "(default)" not in line_with(output, "Partial Group")
        assert "(default)" not in line_with(output, "Extra Field Group")
        assert "(default)" not in line_with(output, "retries")

    def test_json_mode_is_unmarked_raw_values(self, cli_client_factory: CLIClientFactory) -> None:
        """--json emits config_values untouched."""
        routes = [("GET", "/api/config", 200, self.RESPONSE.model_dump())]
        parsed = runner.json_output(cli_client_factory.build_with_routes(routes), cmd_config)
        assert parsed == self.RESPONSE.config_values

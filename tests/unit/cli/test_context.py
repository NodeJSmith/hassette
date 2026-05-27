"""Tests for CLIContext frozen dataclass and injection pipeline."""

import dataclasses
from typing import Annotated
from unittest.mock import patch

import pytest
from cyclopts import App, Parameter

from hassette.cli.client import make_client
from hassette.cli.context import CLIContext
from tests.unit.cli.conftest import CLIClientFactory


class TestCLIContextDefaults:
    def test_defaults(self) -> None:
        ctx = CLIContext()
        assert ctx.json_mode is False
        assert ctx.debug_mode is False
        assert ctx.env_file_override is None
        assert ctx.config_file_override is None


class TestCLIContextFrozen:
    def test_frozen_raises_on_mutation(self) -> None:
        ctx = CLIContext()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.json_mode = True  # pyright: ignore[reportAttributeAccessIssue]


class TestMakeClientReceivesContext:
    def test_make_client_receives_json_mode(self, cli_client_factory: CLIClientFactory) -> None:
        ctx = CLIContext(json_mode=True)
        with patch("hassette.cli.client.HassetteConfig") as mock_config_cls:
            mock_config_cls.return_value = cli_client_factory.config
            mock_config_cls.model_config = {}
            client = make_client(ctx)
        assert client.json_mode is True

    def test_make_client_receives_debug_mode(self, cli_client_factory: CLIClientFactory) -> None:
        ctx = CLIContext(debug_mode=True)
        with patch("hassette.cli.client.HassetteConfig") as mock_config_cls:
            mock_config_cls.return_value = cli_client_factory.config
            mock_config_cls.model_config = {}
            client = make_client(ctx)
        assert client.debug_mode is True

    def test_make_client_no_args_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            make_client()  # pyright: ignore[reportCallIssue]


class TestLauncherInjectsCtx:
    def test_launcher_injects_ctx(self) -> None:
        """Smoke test: verify ctx.json_mode=True is injected into the command when --json is passed.

        Mirrors the real launcher pattern: test_app.meta.default is the launcher,
        invoked via test_app.meta([...]) (same as the real entrypoint's app.meta()).
        """
        received: list[CLIContext] = []

        test_app = App(name="test")

        sub_app = App(name="cmd")
        test_app.command(sub_app)

        @sub_app.default
        def cmd_test(*, ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()) -> None:  # noqa: B008
            received.append(ctx)

        @test_app.meta.default
        def launcher(
            *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
            json: Annotated[bool, Parameter(name=["--json"], negative=[])] = False,
        ) -> None:
            ctx = CLIContext(json_mode=json)
            command, bound, _ignored = test_app.parse_args(tokens)
            bound.arguments["ctx"] = ctx
            command(*bound.args, **bound.kwargs)

        # app.meta() raises SystemExit(0) on success (cyclopts behaviour); catch it.
        with pytest.raises(SystemExit) as exc_info:
            test_app.meta(["--json", "cmd"], exit_on_error=False)
        assert exc_info.value.code == 0

        assert len(received) == 1
        assert received[0].json_mode is True

"""Shared CLI test fixtures for CLI client and command tests."""

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Any, TypedDict, Unpack
from unittest.mock import patch

import httpx2 as httpx
import pytest
from rich.console import Console

import hassette.cli.output as output_module
from hassette.cli.client import HassetteCLIClient
from hassette.cli.context import CLIContext
from hassette.config.config import HassetteConfig
from hassette.test_utils import make_test_config

SINCE_EPOCH = 1_700_000_000.0
NOW_EPOCH = 1_748_000_000.0
REMOTE_SERVER_URL = "https://example.com/hassette"
REMOTE_SERVER_URL_BARE = "https://example.com"


def make_cli_config(
    *,
    host: str = "127.0.0.1",
    port: int = 8126,
    data_dir: Path,
    cli_server_url: str | None = None,
    cli_verify_ssl: bool = True,
    cli_token_file: Path | None = None,
    cli_auth_token: str | None = None,
    web_api_auth_token: str | None = None,
) -> HassetteConfig:
    """Build a HassetteConfig with explicit cli/web_api settings for CLI target/client tests.

    Thin wrapper around the shared ``make_test_config`` factory (see
    ``.claude/rules/test-conventions.md``) that maps this module's cli/web_api-focused keyword
    shape onto ``make_test_config``'s nested-dict overrides, rather than constructing
    ``HassetteConfig`` from scratch. Also inherits ``make_test_config``'s other safety defaults
    (``apps.autodetect=False``, ``disable_state_proxy_polling=True``) since only the ``web_api``
    and ``cli`` groups are overridden here. ``web_api.run=False`` is passed explicitly below
    because supplying a ``web_api=`` override replaces (not merges with) ``make_test_config``'s
    own ``web_api={"run": False}`` default.

    Shared by ``test_target.py`` (resolver/credential precedence tests) and ``test_client.py``
    (HTTP client credential-attachment tests) — both need the same cli/web_api override shape.
    """
    web_api_kwargs: dict[str, Any] = {"host": host, "port": port, "run": False}
    if web_api_auth_token is not None:
        web_api_kwargs["auth_token"] = web_api_auth_token

    cli_kwargs: dict[str, Any] = {"verify_ssl": cli_verify_ssl}
    if cli_server_url is not None:
        cli_kwargs["server_url"] = cli_server_url
    if cli_token_file is not None:
        cli_kwargs["token_file"] = cli_token_file
    if cli_auth_token is not None:
        cli_kwargs["auth_token"] = cli_auth_token

    return make_test_config(data_dir=data_dir, web_api=web_api_kwargs, cli=cli_kwargs)


def fixed_now() -> float:
    return NOW_EPOCH


class GetSpy:
    """Wraps ``client.get`` to record paths and params for assertion.

    Pass as ``side_effect`` to ``patch.object(client, "get", side_effect=spy)``.
    """

    def __init__(self, client: HassetteCLIClient) -> None:
        self.paths: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self._original = client.get

    def __call__(
        self,
        path: str,
        model: type[object],
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> object:
        self.paths.append(path)
        self.calls.append({"path": path, "params": params})
        return self._original(path, model, params=params, **kwargs)

    def params_for(self, path_fragment: str) -> dict[str, Any]:
        """Return the query params of the first recorded GET whose path contains ``path_fragment``.

        Both failure modes name what went wrong: no request matched the fragment (with the paths
        that were actually requested), or the matching request carried no params at all — rather
        than a bare ``StopIteration`` or a ``TypeError`` on ``None``.
        """
        call = next((r for r in self.calls if path_fragment in r["path"]), None)
        assert call is not None, f"no GET path contained {path_fragment!r}; requested paths: {self.paths}"
        params = call["params"]
        assert params is not None, f"GET {call['path']} was issued without query params"
        return dict(params)


@contextmanager
def capture_json_stdout() -> Generator[list[str], None, None]:
    """Capture raw ``sys.stdout.write`` calls (used by JSON-mode commands)."""
    captured: list[str] = []
    with patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)):
        yield captured


def parse_json_stdout(capsys: pytest.CaptureFixture[str]) -> Any:
    """Parse the JSON document a json-mode render wrote to the real stdout.

    For the ``render_*`` functions, which write JSON through ``sys.stdout`` rather than the Rich
    consoles ``capture_stdout()`` patches.
    """
    return json.loads(capsys.readouterr().out)


@contextmanager
def capture_stdout():
    """Capture Rich stdout console output."""
    buf = StringIO()
    mock_console = Console(file=buf, highlight=False, force_terminal=False)
    with patch.object(output_module, "stdout_console", mock_console):
        yield buf


def capture_human(func, *args, **kwargs) -> tuple[str, str]:
    """Call ``func(*args, **kwargs)`` with Rich consoles redirected to StringIO.

    Returns ``(stdout_text, stderr_text)``. This is needed because Rich holds
    a reference to the original sys.stdout at construction time; pytest's
    capsys replacement doesn't intercept it. We patch the module-level consoles.
    """
    stdout_buf = StringIO()
    stderr_buf = StringIO()
    new_stdout = Console(file=stdout_buf, highlight=False, no_color=True)
    new_stderr = Console(file=stderr_buf, highlight=False, no_color=True)
    with (
        patch.object(output_module, "stdout_console", new_stdout),
        patch.object(output_module, "stderr_console", new_stderr),
    ):
        func(*args, **kwargs)
    return stdout_buf.getvalue(), stderr_buf.getvalue()


@contextmanager
def capture_stderr():
    """Capture Rich stderr console output."""
    buf = StringIO()
    mock_console = Console(file=buf, stderr=True, highlight=False, force_terminal=False)
    with patch.object(output_module, "stderr_console", mock_console):
        yield buf


class CommandRunner:
    """Invokes a CLI command function with its module's ``make_client`` patched to a test client.

    Every ``test_commands_*.py`` module builds a mock-backed client, patches the ``make_client``
    its command module imported, runs the command, and reads back one thing: the GET calls it
    made, its human stdout or stderr, the exit it took, or its ``--json`` document. This bundles
    that boilerplate into one call per test. Instantiate once per module — the patch target is
    per-module, since each command module imports ``make_client`` into its own namespace::

        runner = CommandRunner("hassette.cli.commands.log.make_client")

        spy = runner.spy(client, cmd_log, app="my-app")
        output = runner.stdout(client, cmd_log)
        parsed = runner.json_output(client, cmd_log)
        assert "No results" in runner.stderr(client, cmd_log)
        code, stderr = runner.usage_error(client, cmd_log, instance="0")
    """

    def __init__(self, make_client_path: str) -> None:
        self.make_client_path = make_client_path

    def spy(self, client: HassetteCLIClient, func: Callable[..., None], *args: Any, **kwargs: Any) -> GetSpy:
        """Run ``func`` and return the ``GetSpy`` recording its GET paths and params."""
        spy = GetSpy(client)
        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch(self.make_client_path, return_value=client),
        ):
            func(*args, **kwargs)
        return spy

    def stdout(self, client: HassetteCLIClient, func: Callable[..., None], *args: Any, **kwargs: Any) -> str:
        """Run ``func`` and return what it rendered to the human stdout console."""
        with capture_stdout() as buf, patch(self.make_client_path, return_value=client):
            func(*args, **kwargs)
        return buf.getvalue()

    def stderr(self, client: HassetteCLIClient, func: Callable[..., None], *args: Any, **kwargs: Any) -> str:
        """Run ``func`` and return its stderr, with stdout captured so tables don't leak out."""
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch(self.make_client_path, return_value=client),
        ):
            func(*args, **kwargs)
        return err_buf.getvalue()

    def usage_error(
        self, client: HassetteCLIClient, func: Callable[..., None], *args: Any, **kwargs: Any
    ) -> tuple[Any, str]:
        """Run ``func`` expecting it to exit; return the exit code and the stderr it printed.

        Captures stdout for the same reason ``stderr()`` does — whatever the command managed to
        render before exiting shouldn't leak into the test run's own output.
        """
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch(self.make_client_path, return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            func(*args, **kwargs)
        return exc_info.value.code, err_buf.getvalue()

    def json_output(self, client: HassetteCLIClient, func: Callable[..., None], *args: Any, **kwargs: Any) -> Any:
        """Run ``func`` in JSON mode and return its parsed stdout document.

        The json-mode ``ctx`` is supplied here, so call sites pass only the command's own args.
        """
        with (
            patch(self.make_client_path, return_value=client),
            capture_json_stdout() as captured,
        ):
            func(*args, ctx=CLIContext(json_mode=True), **kwargs)
        return json.loads("".join(captured))


class MockTransportBuilder:
    """Builds an httpx2.MockTransport from a route table.

    Usage:
        builder = MockTransportBuilder()
        builder.add("GET", "/api/health", 200, {"status": "ok"})
        transport = builder.build()
    """

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, int, Any]] = []
        self.captured_headers: list[httpx.Headers] = []

    def add(self, method: str, path_fragment: str, status: int, body: Any) -> None:
        """Register a mock response for requests whose URL contains ``path_fragment``.

        The first matching route wins.
        """
        self._routes.append((method.upper(), path_fragment, status, body))

    def build(self) -> httpx.MockTransport:
        """Build the transport.

        Every request's headers are recorded to ``self.captured_headers`` in order,
        regardless of which route (if any) matched.
        """
        routes = list(self._routes)

        def handler(request: httpx.Request) -> httpx.Response:
            self.captured_headers.append(request.headers)
            url = str(request.url)
            method = request.method.upper()
            for route_method, fragment, status, body in routes:
                if route_method == method and fragment in url:
                    content = json.dumps(body).encode()
                    return httpx.Response(status, content=content, headers={"content-type": "application/json"})
            return httpx.Response(
                404,
                content=json.dumps({"detail": f"No mock route for {method} {url}"}).encode(),
                headers={"content-type": "application/json"},
            )

        return httpx.MockTransport(handler)


class ClientFlags(TypedDict, total=False):
    """The keyword-only resolver inputs ``HassetteCLIClient.__init__`` accepts.

    Mirrors what ``make_client(ctx)`` unpacks from ``CLIContext`` in real usage — pass these
    through any ``CLIClientFactory`` builder to test flag-sourced targets, credentials, or TLS
    settings without hand-building a ``CLIContext``. Declared once here so the builders below
    forward the list as ``**flags`` instead of each restating it.
    """

    debug_mode: bool
    server_url_flag: str | None
    token_file_flag: Path | None
    verify_ssl_flag: bool | None


class CLIClientFactory:
    """Creates HassetteCLIClient instances with mock transports for testing."""

    def __init__(self, config: HassetteConfig | None = None) -> None:
        self.config = config if config is not None else HassetteConfig(token=None)

    def build(
        self,
        transport: httpx.BaseTransport,
        json_mode: bool = False,
        **flags: Unpack[ClientFlags],
    ) -> HassetteCLIClient:
        """Build a HassetteCLIClient backed by ``transport``."""
        return HassetteCLIClient(self.config, json_mode=json_mode, transport=transport, **flags)

    def build_with_routes(
        self,
        routes: list[tuple[str, str, int, Any]],
        json_mode: bool = False,
        **flags: Unpack[ClientFlags],
    ) -> HassetteCLIClient:
        """Build a client pre-wired with route responses.

        Args:
            routes: List of ``(method, path_fragment, status, body)`` tuples.
            json_mode: Whether the client operates in JSON mode.
            flags: Resolver inputs forwarded to the client — see ``ClientFlags``.
        """
        builder = MockTransportBuilder()
        for method, path_fragment, status, body in routes:
            builder.add(method, path_fragment, status, body)
        return self.build(builder.build(), json_mode=json_mode, **flags)

    def build_capturing_headers(
        self,
        status_code: int = 200,
        body: Any = None,
        json_mode: bool = False,
        **flags: Unpack[ClientFlags],
    ) -> tuple[HassetteCLIClient, list[httpx.Headers]]:
        """Build a client whose mock transport returns a fixed response for every GET request.

        Returns the client and a list that accumulates ``httpx.Headers`` for each request made
        through it, in order — for tests asserting on outgoing request headers (e.g. credential
        attachment).
        """
        builder = MockTransportBuilder()
        builder.add("GET", "", status_code, body if body is not None else {})
        client = self.build(builder.build(), json_mode=json_mode, **flags)
        return client, builder.captured_headers


@pytest.fixture
def cli_client_factory() -> CLIClientFactory:
    """Provide a CLIClientFactory for creating mock-backed CLI clients.

    Example usage in a command test::

        def test_status_command(cli_client_factory):
            client = cli_client_factory.build_with_routes([
                ("GET", "/api/health", 200, {"status": "ok", ...}),
            ])
            # call command with client

    Tests that need a non-default config (e.g. a ``tmp_path``-scoped ``data_dir`` or an
    explicit ``auth_token``) should construct their own ``CLIClientFactory(config)`` instead
    of using this fixture — the fixture's config is fixed at ``HassetteConfig(token=None)``.
    """
    return CLIClientFactory()

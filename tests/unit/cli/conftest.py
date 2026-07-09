"""Shared CLI test fixtures for CLI client and command tests."""

import json
from contextlib import contextmanager
from io import StringIO
from typing import Any
from unittest.mock import patch

import httpx2 as httpx
import pytest
from rich.console import Console

import hassette.cli.output as output_module
from hassette.cli.client import HassetteCLIClient
from hassette.config.config import HassetteConfig


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


class MockTransportBuilder:
    """Builds an httpx2.MockTransport from a route table.

    Usage:
        builder = MockTransportBuilder()
        builder.add("GET", "/api/health", 200, {"status": "ok"})
        transport = builder.build()
    """

    def __init__(self) -> None:
        self._routes: list[tuple[str, str, int, Any]] = []

    def add(self, method: str, path_fragment: str, status: int, body: Any) -> None:
        """Register a mock response for requests whose URL contains ``path_fragment``.

        The first matching route wins.
        """
        self._routes.append((method.upper(), path_fragment, status, body))

    def build(self) -> httpx.MockTransport:
        routes = list(self._routes)

        def handler(request: httpx.Request) -> httpx.Response:
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


class CLIClientFactory:
    """Creates HassetteCLIClient instances with mock transports for testing."""

    def __init__(self) -> None:
        self.config = HassetteConfig(token=None)

    def build(
        self,
        transport: httpx.BaseTransport,
        json_mode: bool = False,
    ) -> HassetteCLIClient:
        """Build a HassetteCLIClient backed by ``transport``."""
        return HassetteCLIClient(self.config, json_mode=json_mode, transport=transport)

    def build_with_routes(
        self,
        routes: list[tuple[str, str, int, Any]],
        json_mode: bool = False,
    ) -> HassetteCLIClient:
        """Build a client pre-wired with route responses.

        Args:
            routes: List of ``(method, path_fragment, status, body)`` tuples.
            json_mode: Whether the client operates in JSON mode.
        """
        builder = MockTransportBuilder()
        for method, path_fragment, status, body in routes:
            builder.add(method, path_fragment, status, body)
        transport = builder.build()
        return self.build(transport, json_mode=json_mode)


@pytest.fixture
def cli_client_factory() -> CLIClientFactory:
    """Provide a CLIClientFactory for creating mock-backed CLI clients.

    Example usage in a command test::

        def test_status_command(cli_client_factory):
            client = cli_client_factory.build_with_routes([
                ("GET", "/api/health", 200, {"status": "ok", ...}),
            ])
            # call command with client
    """
    return CLIClientFactory()

"""HTTP client wrapper for hassette CLI commands.

Wraps ``httpx.Client`` (synchronous) with:
- Base URL construction from HassetteConfig (bind-all address substitution)
- Explicit timeouts on every request
- Pydantic model deserialization
- Structured error handling (human mode: Rich on stderr; JSON mode: stdout JSON)
- ``--app`` endpoint routing (global vs. per-app telemetry paths)
- ``--instance`` name-to-index resolution via manifest lookup
"""

import json
import sys
from typing import Any, NoReturn, TypeVar, overload

import httpx

import hassette.cli.output as cli_output
from hassette.cli.context import CLIContext
from hassette.config.config import HassetteConfig
from hassette.web.models import AppManifestListResponse

DEFAULT_TIMEOUT = 10.0

# Bind-all addresses that are not routable as connect targets
_BIND_ALL_SUBSTITUTIONS: dict[str, str] = {
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
}

T = TypeVar("T")


def _substitute_host(host: str) -> str:
    """Replace bind-all addresses with loopback equivalents."""
    return _BIND_ALL_SUBSTITUTIONS.get(host, host)


def _format_host(host: str) -> str:
    """Wrap IPv6 addresses in brackets for use in URLs."""
    substituted = _substitute_host(host)
    if ":" in substituted:
        return f"[{substituted}]"
    return substituted


class HassetteCLIClient:
    """Synchronous HTTP client for querying the hassette REST API."""

    def __init__(
        self,
        config: HassetteConfig,
        json_mode: bool,
        debug_mode: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        host = _format_host(config.web_api.host)
        port = config.web_api.port
        self.base_url = f"http://{host}:{port}"
        self.json_mode = json_mode
        self.debug_mode = debug_mode
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, transport=transport)

    def close(self) -> None:
        self._client.close()

    # ---------------------------------------------------------------------------
    # Core request method
    # ---------------------------------------------------------------------------

    @overload
    def get(
        self, path: str, model: type[dict], params: dict[str, Any] | None = None, *, tolerate_503: bool = False
    ) -> dict[str, Any]: ...

    @overload
    def get(
        self, path: str, model: type[list], params: dict[str, Any] | None = None, *, tolerate_503: bool = False
    ) -> list[Any]: ...

    @overload
    def get(
        self, path: str, model: type[T], params: dict[str, Any] | None = None, *, tolerate_503: bool = False
    ) -> T: ...

    def get(
        self,
        path: str,
        model: type[T],
        params: dict[str, Any] | None = None,
        *,
        tolerate_503: bool = False,
    ) -> T | dict[str, Any] | list[Any]:
        """Perform a GET request, deserialize the response, and handle errors.

        Args:
            model: Pydantic model class or ``list``/``dict`` for raw responses.
            tolerate_503: When ``True``, a 503 response is deserialized and returned
                rather than treated as an error. Use for human-inspection commands
                whose endpoint returns 503 with a valid status body (e.g. a degraded
                telemetry DB). The body is the source of truth, not the HTTP status.

        Raises:
            SystemExit: On HTTP 4xx/5xx (code 1) or network errors (code 2). A 503 is
                exempt from the error path when ``tolerate_503=True``.
        """
        try:
            response = self._client.get(path, params=params, timeout=self.timeout)
        except httpx.ConnectError as exc:
            self._handle_network_error(f"Connection refused: {self.base_url} ({exc})")
        except httpx.TimeoutException:
            self._handle_network_error(f"Request timed out after {self.timeout}s connecting to {self.base_url}")
        except httpx.RequestError as exc:
            self._handle_network_error(f"Network error: {exc}")

        is_tolerated_503 = tolerate_503 and response.status_code == 503
        if not response.is_success and not is_tolerated_503:
            self._handle_http_error(response)

        data = response.json()
        if model is dict or model is list:
            return data
        return model.model_validate(data)  # pyright: ignore[reportAttributeAccessIssue]

    # ---------------------------------------------------------------------------
    # App routing & instance resolution
    # ---------------------------------------------------------------------------

    def get_with_app_routing(
        self,
        global_path: str,
        per_app_path_template: str,
        model: type[T],
        app_key: str | None = None,
        instance: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> T:
        """Perform a GET request with ``--app`` and ``--instance`` routing.

        - No ``app_key``: uses ``global_path``
        - ``app_key`` only: uses ``per_app_path_template.format(app_key=app_key)``
        - ``instance`` without ``app_key``: usage error, exits non-zero
        - ``instance`` + ``app_key``: resolves instance to index, adds ``instance_index`` param

        Args:
            global_path: API path for the global (no app filter) case.
            per_app_path_template: API path template with ``{app_key}`` placeholder.
            model: Pydantic model class or ``list``/``dict`` for raw responses.
            app_key: Optional app key filter.
            instance: Optional instance selector (integer string or name).
            extra_params: Additional query parameters to include.

        Returns:
            Deserialized response.
        """
        params: dict[str, Any] = dict(extra_params or {})

        if instance is not None and app_key is None:
            self.error_usage("--instance requires --app to be specified")

        if app_key is None:
            path = global_path
        else:
            path = per_app_path_template.format(app_key=app_key)

            if instance is not None:
                instance_index = self.resolve_instance(app_key, instance)
                params["instance_index"] = instance_index

        return self.get(path, model, params=params)

    def resolve_instance(self, app_key: str, instance: str) -> int:
        """Resolve an instance selector to an integer index.

        Args:
            app_key: The app key to look up.
            instance: Either a digit string (e.g. ``"1"``) or an instance name.

        Returns:
            The resolved instance index.

        Raises:
            SystemExit: If ``instance`` is a name that doesn't match any instance.
        """
        try:
            return int(instance)
        except ValueError:
            pass

        # Name resolution — fetch all manifests and filter client-side for the given app_key
        manifest_list = self.get("/api/apps/manifests", AppManifestListResponse)
        for manifest in manifest_list.manifests:
            if manifest.app_key != app_key:
                continue
            for inst in manifest.instances:
                if inst.instance_name == instance:
                    return inst.index

        available = []
        for manifest in manifest_list.manifests:
            if manifest.app_key == app_key:
                available.extend(inst.instance_name for inst in manifest.instances)
        names = ", ".join(repr(n) for n in available) if available else "(none)"
        self.error_usage(f"Instance {instance!r} not found for app {app_key!r}. Available instances: {names}")
        raise AssertionError("unreachable")

    # ---------------------------------------------------------------------------
    # Error helpers
    # ---------------------------------------------------------------------------

    def _handle_http_error(self, response: httpx.Response) -> NoReturn:
        """Print HTTP error and exit with code 1."""
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text

        if self.json_mode:
            extra = {"url": str(response.url), "method": response.request.method, "body": response.text}
            _write_json_error(response.status_code, str(detail), debug_extra=extra if self.debug_mode else None)
        else:
            cli_output.stderr_console.print(f"[bold red]Error {response.status_code}:[/bold red] {detail}")
            if self.debug_mode:
                cli_output.stderr_console.print(f"  [dim]URL:[/dim]    {response.request.method} {response.url}")
                cli_output.stderr_console.print(f"  [dim]Body:[/dim]   {response.text}")
        sys.exit(1)

    def _handle_network_error(self, message: str) -> NoReturn:
        """Print a network error and exit with code 2."""
        if self.json_mode:
            _write_json_error(None, message)
        else:
            cli_output.stderr_console.print(f"[bold red]Network error:[/bold red] {message}")
        sys.exit(2)

    def error_usage(self, message: str) -> NoReturn:
        """Print a usage error and exit non-zero."""
        if self.json_mode:
            _write_json_error(None, message)
        else:
            cli_output.stderr_console.print(f"[bold red]Usage error:[/bold red] {message}", highlight=False)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def make_client(ctx: CLIContext) -> HassetteCLIClient:
    """Create a CLI client from the default config (no HA token required).

    Args:
        ctx: The CLI context for this invocation, carrying output mode and
            config file override paths.
    """
    config = HassetteConfig(token=None)
    return HassetteCLIClient(config, json_mode=ctx.json_mode, debug_mode=ctx.debug_mode)


def _write_json_error(status: int | None, detail: str, debug_extra: dict[str, Any] | None = None) -> None:
    """Write a JSON error document to stdout."""
    doc: dict[str, Any] = {"error": True, "status": status, "detail": detail}
    if debug_extra:
        doc["debug"] = debug_extra
    sys.stdout.write(json.dumps(doc) + "\n")
    sys.stdout.flush()

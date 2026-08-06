"""HTTP client wrapper for hassette CLI commands.

Wraps ``httpx2.Client`` (synchronous) with:
- Base URL construction from HassetteConfig (bind-all address substitution)
- Explicit timeouts on every request
- Pydantic model deserialization
- Structured error handling (human mode: Rich on stderr; JSON mode: stdout JSON)
- ``--app`` endpoint routing (global vs. per-app telemetry paths)
- ``--instance`` name-to-index resolution via manifest lookup
"""

import json
import sys
from pathlib import Path
from typing import Any, NoReturn, TypeVar, overload

import httpx2 as httpx

import hassette.cli.output as cli_output
from hassette.cli.context import CLIContext
from hassette.cli.target import resolve_cli_auth_token, resolve_server_target
from hassette.config.config import HassetteConfig
from hassette.exceptions import FatalError
from hassette.web.models import AppManifestListResponse

DEFAULT_TIMEOUT = 10.0

T = TypeVar("T")


class HassetteCLIClient:
    """Synchronous HTTP client for querying the hassette REST API."""

    def __init__(
        self,
        config: HassetteConfig,
        json_mode: bool,
        debug_mode: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        server_url_flag: str | None = None,
        token_file_flag: Path | None = None,
        verify_ssl_flag: bool | None = None,
    ) -> None:
        # Set before any resolution runs so a FatalError raised below (bad --server-url,
        # unreadable --token-file, a non-header-safe credential) renders via error_usage()
        # in the right format instead of a bare traceback.
        self.json_mode = json_mode
        self.debug_mode = debug_mode
        self.timeout = timeout
        self._success_echoed = False

        try:
            target = resolve_server_target(config, server_url_flag=server_url_flag, verify_ssl_flag=verify_ssl_flag)
            token = resolve_cli_auth_token(config, target, token_file_flag=token_file_flag)
        except FatalError as exc:
            self.error_usage(str(exc))

        self.base_url = target.base_url
        self.is_loopback = target.is_loopback
        # verify_ssl ended up False without an explicit --no-verify-ssl/--verify-ssl flag on
        # this invocation, so it came from cli.verify_ssl in config — a silent, durable
        # opt-out rather than a conscious per-invocation choice.
        self._insecure_from_config = not target.verify_ssl and verify_ssl_flag is None
        self._token_resolved = bool(token)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=self.base_url, transport=transport, headers=headers, verify=target.verify_ssl
        )

    def close(self) -> None:
        self._client.close()

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

        try:
            data = response.json()
            if model is dict or model is list:
                result: Any = data
            else:
                result = model.model_validate(data)  # pyright: ignore[reportAttributeAccessIssue]
        except ValueError:
            # A tolerated 503 can carry a body that isn't the expected status
            # payload — a proxy/LB HTML error page (non-JSON) or JSON of the wrong
            # shape. pydantic.ValidationError is a ValueError, so both land here.
            # Route them to the normal error exit instead of crashing.
            if is_tolerated_503:
                self._handle_http_error(response)
            raise

        self._echo_success_target_and_warnings()
        return result

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

    def _echo_success_target_and_warnings(self) -> None:
        """Surface the resolved non-loopback target and any TLS-verification warning once per
        invocation on the success path.

        JSON mode is deliberately left untouched here. Every command's ``get()`` result flows
        straight into a render function (``render_table``/``render_detail``/etc. in
        ``cli/output.py``) that owns the one JSON document written to stdout for that command —
        there is no shared success envelope to add a ``"target"``/``"tls_verified"`` key to
        without restructuring every command's JSON output path, which is out of scope here. See
        the design doc's Architecture -> "Failing open, not fast" for the intended shape; this
        is a known, called-out gap, not an oversight.
        """
        if self.json_mode or self._success_echoed:
            return
        self._success_echoed = True
        if not self.is_loopback:
            cli_output.stderr_console.print(f"[dim]Target:[/dim] {self.base_url}", highlight=False)
        if self._insecure_from_config:
            self._print_tls_warning()

    def _print_tls_warning(self) -> None:
        """Print the "TLS verification is disabled" warning for the current ``base_url``."""
        cli_output.stderr_console.print(
            f"[bold yellow]Warning:[/bold yellow] TLS verification is disabled for {self.base_url} "
            "(cli.verify_ssl = false in config).",
            highlight=False,
        )

    def _handle_http_error(self, response: httpx.Response) -> NoReturn:
        """Print HTTP error and exit with code 1."""
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text

        if response.status_code == 401 and not self._token_resolved:
            if self.is_loopback:
                # No config value and no token file — distinguish this from "token was
                # wrong" so the operator isn't left guessing why an unauthenticated
                # request failed.
                detail = f"{detail} (no auth token found — has hassette been started?)"
            else:
                # A server-scoped credential source was suppressed for this remote target —
                # separate the remedies by where they apply, since one is local (attach a
                # credential) and the other is remote (reconfigure the instance being queried).
                detail = (
                    f"{detail} (no credential was attached to this remote request. Attach one "
                    "locally via --token-file, cli.token_file, or the HASSETTE__CLI__AUTH_TOKEN "
                    "environment variable — or, if this target sits behind a forward-auth proxy, "
                    "configure trusted_proxies on the remote instance, which requires access to "
                    "that host and a restart)"
                )
        elif 300 <= response.status_code < 400:
            detail = (
                f"{detail} (this response is a redirect — likely a forward-auth login page in "
                "front of the target, not Hassette itself. See the reverse-proxy section of the "
                "CLI configuration docs.)"
            )

        target, tls_verified = self._target_and_tls_for_error()

        if self.json_mode:
            extra = (
                {"url": str(response.url), "method": response.request.method, "body": response.text}
                if self.debug_mode
                else None
            )
            _write_json_error(
                response.status_code, str(detail), debug_extra=extra, target=target, tls_verified=tls_verified
            )
        else:
            cli_output.stderr_console.print(f"[bold red]Error {response.status_code}:[/bold red] {detail}")
            if target is not None:
                cli_output.stderr_console.print(f"[dim]Target:[/dim] {target}", highlight=False)
            if tls_verified is False:
                self._print_tls_warning()
            if self.debug_mode:
                cli_output.stderr_console.print(f"  [dim]URL:[/dim]    {response.request.method} {response.url}")
                cli_output.stderr_console.print(f"  [dim]Body:[/dim]   {response.text}")
        sys.exit(1)

    def _handle_network_error(self, message: str) -> NoReturn:
        """Print a network error and exit with code 2."""
        target, tls_verified = self._target_and_tls_for_error()
        if self.json_mode:
            _write_json_error(None, message, target=target, tls_verified=tls_verified)
        else:
            cli_output.stderr_console.print(f"[bold red]Network error:[/bold red] {message}")
            if tls_verified is False:
                self._print_tls_warning()
        sys.exit(2)

    def _target_and_tls_for_error(self) -> tuple[str | None, bool | None]:
        """Derive the JSON-error envelope's ``target``/``tls_verified`` fields.

        Shared by :meth:`_handle_http_error` and :meth:`_handle_network_error` so the
        loopback-suppression and config-vs-flag TLS logic has a single source of truth.
        """
        target = self.base_url if not self.is_loopback else None
        tls_verified = False if self._insecure_from_config else None
        return target, tls_verified

    def error_usage(self, message: str) -> NoReturn:
        """Print a usage error and exit non-zero."""
        if self.json_mode:
            _write_json_error(None, message)
        else:
            cli_output.stderr_console.print(f"[bold red]Usage error:[/bold red] {message}", highlight=False)
        sys.exit(1)


def make_client(ctx: CLIContext) -> HassetteCLIClient:
    """Create a CLI client from the default config (no HA token required).

    The single place that unpacks a :class:`CLIContext` into the keyword arguments
    :func:`hassette.cli.target.resolve_server_target` and
    :func:`hassette.cli.target.resolve_cli_auth_token` accept.

    Args:
        ctx: The CLI context for this invocation, carrying output mode, config file
            override paths, and the remote-target flags (``--server-url``,
            ``--token-file``, ``--no-verify-ssl``/``--verify-ssl``).
    """
    config = HassetteConfig(token=None)
    return HassetteCLIClient(
        config,
        json_mode=ctx.json_mode,
        debug_mode=ctx.debug_mode,
        server_url_flag=ctx.server_url,
        token_file_flag=ctx.token_file,
        verify_ssl_flag=ctx.verify_ssl,
    )


def _write_json_error(
    status: int | None,
    detail: str,
    debug_extra: dict[str, Any] | None = None,
    target: str | None = None,
    tls_verified: bool | None = None,
) -> None:
    """Write a JSON error document to stdout."""
    doc: dict[str, Any] = {"error": True, "status": status, "detail": detail}
    if target is not None:
        doc["target"] = target
    if tls_verified is not None:
        doc["tls_verified"] = tls_verified
    if debug_extra:
        doc["debug"] = debug_extra
    sys.stdout.write(json.dumps(doc) + "\n")
    sys.stdout.flush()

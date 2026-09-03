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
from typing import Any, Literal, NoReturn, TypeVar, overload

import httpx2 as httpx
from pydantic import ValidationError

import hassette.cli.output as cli_output
from hassette.cli.context import CLIContext
from hassette.cli.target import resolve_cli_auth_token, resolve_server_target
from hassette.config.config import HassetteConfig
from hassette.exceptions import FatalError
from hassette.web.models import ActionResponse, AppInstanceResponse, AppManifestListResponse

DEFAULT_TIMEOUT = 10.0

T = TypeVar("T")


def _filter_instances(manifest_list: AppManifestListResponse, app_key: str) -> list[AppInstanceResponse]:
    """Flatten the instance list for ``app_key`` out of a full manifest list response.

    Shared by :meth:`HassetteCLIClient._fetch_instances` and
    :meth:`HassetteCLIClient._try_fetch_instances` so the filter has one source of truth.
    """
    return [inst for manifest in manifest_list.manifests if manifest.app_key == app_key for inst in manifest.instances]


def query_params(**values: Any) -> dict[str, Any]:
    """Build a query-parameter dict from CLI flags, dropping every flag left unset.

    Commands share one convention: an unset flag is ``None`` and must not reach the server,
    so the endpoint applies its own default. Writing that as ``query_params(since=since,
    limit=limit)`` keeps the mapping from flag to query key on one line per command instead
    of an ``if x is not None`` block per flag.
    """
    return {key: value for key, value in values.items() if value is not None}


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

    def _send(self, method: Literal["GET", "POST"], path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Perform an HTTP request, translating transport failures into a usage-error exit.

        Shared by :meth:`get` and :meth:`post` — the only difference between the two verbs
        is what happens to the response afterward (status/503 handling, deserialization
        target), not how connection failures become a ``SystemExit``. :meth:`_try_fetch_instances`
        is the one intentional exception: it needs failures to return ``None`` rather than exit,
        so it calls ``self._client`` directly instead of going through this method.
        """
        try:
            if method == "GET":
                response = self._client.get(path, params=params, timeout=self.timeout)
            else:
                response = self._client.post(path, timeout=self.timeout)
        except httpx.ConnectError as exc:
            self._handle_network_error(f"Connection refused: {self.base_url} ({exc})")
        except httpx.TimeoutException:
            self._handle_network_error(f"Request timed out after {self.timeout}s connecting to {self.base_url}")
        except httpx.RequestError as exc:
            self._handle_network_error(f"Network error: {exc}")
        return response

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
            SystemExit: On HTTP 4xx/5xx (code 1), network errors (code 2), or a
                successful-looking response whose body is not valid JSON or doesn't match
                ``model`` (code 1). A 503 is exempt from the error path when
                ``tolerate_503=True``.
        """
        response = self._send("GET", path, params=params)

        is_tolerated_503 = tolerate_503 and response.status_code == 503
        if not response.is_success and not is_tolerated_503:
            self._handle_http_error(response)

        try:
            data = response.json()
            if model is dict or model is list:
                result: Any = data
            else:
                result = model.model_validate(data)  # pyright: ignore[reportAttributeAccessIssue]
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            # A tolerated 503 can carry a body that isn't the expected status
            # payload — a proxy/LB HTML error page (non-JSON) or JSON of the wrong
            # shape. Route it to the normal HTTP-error exit instead of crashing.
            # UnicodeDecodeError covers a 2xx/tolerated-503 body that isn't valid UTF-8 —
            # response.json() decodes before parsing, so malformed bytes raise this instead
            # of JSONDecodeError.
            if is_tolerated_503:
                self._handle_http_error(response)
            # Any other successful-looking response (2xx) with an unusable body means the
            # CLI isn't actually talking to a compatible hassette instance — wrong
            # --server-url (an unrelated service or reverse proxy answering with a 200), or
            # CLI/server version skew. Surface that as a clean CLI error instead of letting
            # the parse exception propagate as a raw traceback.
            self._handle_malformed_response(response, exc)

        self._echo_success_target_and_warnings()
        return result

    def post(self, path: str) -> ActionResponse:
        """Perform a POST request to an app mutation endpoint, deserialize, and handle errors.

        Action routes (start/stop/reload) take no request body or query params and always
        respond with an :class:`~hassette.web.models.ActionResponse` on success.

        Raises:
            SystemExit: On HTTP 4xx/5xx (code 1), network errors (code 2), or a
                successful-looking response whose body is not valid JSON or doesn't match
                ``ActionResponse`` (code 1).
        """
        response = self._send("POST", path)

        if not response.is_success:
            self._handle_http_error(response)

        try:
            result = ActionResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            # Mirrors get()'s malformed-response handling above — a 2xx response we can't
            # parse into an ActionResponse means the same thing there does: wrong
            # --server-url, or CLI/server version skew.
            self._handle_malformed_response(response, exc)

        self._echo_success_target_and_warnings()
        return result

    def post_with_instance_routing(
        self, app_key: str, action: str, instance_index: int | None = None
    ) -> ActionResponse:
        """Perform a POST to an app mutation endpoint, routing to the app- or instance-scoped path.

        Mirrors :meth:`get_with_app_routing`'s app-level-vs-instance-scoped path selection, but
        for POST action endpoints (start/stop/reload), which take an already-resolved instance
        index rather than a raw selector string. Unlike the GET side, resolving the selector
        can't happen inside this method: the caller needs the resolved index (and canonical
        name, via :meth:`resolve_instance_with_name`) to build a confirmation prompt *before*
        this mutating POST runs.

        Args:
            app_key: The app key to act on.
            action: One of ``"start"``, ``"stop"``, ``"reload"``.
            instance_index: The already-resolved instance index, or ``None`` for an app-level
                action.

        Returns:
            The deserialized :class:`~hassette.web.models.ActionResponse`.
        """
        path = (
            f"/api/apps/{app_key}/{action}"
            if instance_index is None
            else f"/api/apps/{app_key}/instances/{instance_index}/{action}"
        )
        return self.post(path)

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

    def _fetch_instances(self, app_key: str) -> list[AppInstanceResponse]:
        """Fetch all manifests and return the instance list for ``app_key``."""
        manifest_list = self.get("/api/apps/manifests", AppManifestListResponse)
        return _filter_instances(manifest_list, app_key)

    def _try_fetch_instances(self, app_key: str) -> list[AppInstanceResponse] | None:
        """Best-effort variant of :meth:`_fetch_instances` that never exits the process.

        ``/api/apps/manifests`` is a Category B endpoint that returns 503 when the
        telemetry DB is unavailable. Resolving a numeric ``--instance`` selector to its
        canonical name is a purely cosmetic lookup — the mutating start/stop/reload
        action it supports has no telemetry dependency of its own — so a telemetry
        outage must not block that action. Use this instead of :meth:`_fetch_instances`
        wherever the caller has a numeric-index fallback available; any failure here
        (network error, non-2xx status, unparseable body) returns ``None`` rather than
        calling ``sys.exit``.
        """
        try:
            response = self._client.get("/api/apps/manifests", timeout=self.timeout)
        except httpx.RequestError:
            return None

        if not response.is_success:
            return None

        try:
            manifest_list = AppManifestListResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError):
            return None

        return _filter_instances(manifest_list, app_key)

    def _instance_not_found(self, app_key: str, instance: str, instances: list[AppInstanceResponse]) -> NoReturn:
        names = ", ".join(repr(inst.instance_name) for inst in instances) if instances else "(none)"
        self.error_usage(f"Instance {instance!r} not found for app {app_key!r}. Available instances: {names}")
        raise AssertionError("unreachable")

    def _find_by_name(
        self, app_key: str, instances: list[AppInstanceResponse], name: str
    ) -> AppInstanceResponse | None:
        """Return the instance whose ``instance_name`` matches ``name``, or ``None``.

        Config validation permits two configured instances to share an ``instance_name`` —
        raises via ``error_usage()`` on more than one match rather than silently acting on
        whichever one happens to come first, since that would stop/reload/start an arbitrary
        sibling instance while reporting that the requested name was acted on.
        """
        matches = [inst for inst in instances if inst.instance_name == name]
        if len(matches) > 1:
            indices = ", ".join(str(inst.index) for inst in matches)
            self.error_usage(
                f"Instance name {name!r} is ambiguous for app {app_key!r} — matches indices "
                f"{indices}. Use --instance <index> instead."
            )
        return matches[0] if matches else None

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

        instances = self._fetch_instances(app_key)
        match = self._find_by_name(app_key, instances, instance)
        if match is not None:
            return match.index
        self._instance_not_found(app_key, instance, instances)
        raise AssertionError("unreachable")

    def resolve_instance_with_name(self, app_key: str, instance: str) -> tuple[int, str | None]:
        """Resolve an instance selector to its index and, when known, its canonical ``instance_name``.

        For a name selector, this always fetches the manifest — there is no fallback,
        since without it there is no way to resolve which index the name refers to.

        For a digit selector, the manifest name lookup is best-effort: it resolves to
        the canonical ``instance_name`` when possible so a caller building a
        human-facing message can report the same instance identity regardless of which
        selector flavor the operator used, but it tolerates the manifest fetch failing
        outright (e.g. a 503 from a degraded telemetry DB — see
        :meth:`_try_fetch_instances`) the same way it already tolerates a manifest with
        no matching index: both fall back to the raw selector. A numeric selector's
        underlying mutating action (start/stop/reload) has no telemetry dependency of
        its own, so a telemetry outage must not block it.

        Args:
            app_key: The app key to look up.
            instance: Either a digit string (e.g. ``"1"``) or an instance name.

        Returns:
            ``(index, instance_name)``. For a name selector, ``instance_name`` is never
            ``None`` — an unmatched name raises instead (see below). For a digit
            selector, ``None`` means "resolved, but unverified against the current
            manifest" — not "not found": the index is still returned as-is.

        Raises:
            SystemExit: If ``instance`` is a name that doesn't match any known instance.
        """
        try:
            index = int(instance)
        except ValueError:
            instances = self._fetch_instances(app_key)
            match = self._find_by_name(app_key, instances, instance)
            if match is not None:
                return match.index, match.instance_name
            self._instance_not_found(app_key, instance, instances)
            raise AssertionError("unreachable") from None
        else:
            instances = self._try_fetch_instances(app_key)
            if instances is not None:
                for inst in instances:
                    if inst.index == index:
                        return inst.index, inst.instance_name
            # No manifest entry for this index (out-of-range, or a race with a manifest
            # change), or the manifest fetch itself failed — resolved, not
            # unverified-as-in-not-found; see Returns above.
            return index, None

    def resolve_instance_or_none(self, app_key: str, instance: str | None) -> int | None:
        """Resolve an instance selector, passing ``None`` through unchanged.

        Convenience wrapper for CLI commands where an unset ``--instance`` flag means
        "all instances" and should stay ``None`` rather than resolve to an index.
        """
        return None if instance is None else self.resolve_instance(app_key, instance)

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

    def _handle_malformed_response(self, response: httpx.Response, exc: Exception) -> NoReturn:
        """Print a clean error for a successful-status response whose body isn't usable.

        Reached when the HTTP status looked successful (2xx, or a tolerated 503) but the body
        is not valid JSON or doesn't match the expected model. Both point at the same root
        cause: the CLI isn't actually talking to a compatible hassette instance — wrong
        ``--server-url`` (a reverse proxy or unrelated service answering with a 200 HTML page)
        or CLI/server version skew. Exits like any other error path instead of letting the
        parse exception surface as a raw traceback.
        """
        if isinstance(exc, json.JSONDecodeError):
            reason = "the response body is not valid JSON"
        elif isinstance(exc, UnicodeDecodeError):
            reason = "the response body is not valid UTF-8"
        else:
            reason = f"the response body does not match the expected shape ({exc})"
        detail = (
            f"response from {response.url} is not a valid hassette API response — {reason}. "
            "Check --server-url and for CLI/server version skew."
        )

        target, tls_verified = self._target_and_tls_for_error()
        # response.text re-triggers the same decode failure for a UnicodeDecodeError body, so the
        # debug body dump below must not rely on it — decode leniently instead.
        body = response.content.decode("utf-8", errors="replace")

        if self.json_mode:
            extra = (
                {"url": str(response.url), "method": response.request.method, "body": body} if self.debug_mode else None
            )
            _write_json_error(response.status_code, detail, debug_extra=extra, target=target, tls_verified=tls_verified)
        else:
            cli_output.stderr_console.print(f"[bold red]Error:[/bold red] {detail}", highlight=False)
            if target is not None:
                cli_output.stderr_console.print(f"[dim]Target:[/dim] {target}", highlight=False)
            if tls_verified is False:
                self._print_tls_warning()
            if self.debug_mode:
                cli_output.stderr_console.print(f"  [dim]URL:[/dim]    {response.request.method} {response.url}")
                cli_output.stderr_console.print(f"  [dim]Body:[/dim]   {body}")
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

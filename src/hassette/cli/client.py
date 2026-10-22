"""HTTP client wrapper for hassette CLI commands.

Wraps ``httpx2.Client`` (synchronous) with:
- Base URL construction from HassetteConfig (bind-all address substitution)
- Explicit timeouts on every request
- Pydantic model deserialization
- Structured error handling (human mode: Rich on stderr; JSON mode: stdout JSON)
- ``--app`` endpoint routing (global vs. per-app telemetry paths)
- ``--instance`` name-to-index resolution via app list lookup
"""

import json
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal, NoReturn, TypeVar, overload

import httpx2 as httpx
from hassette_wire import LENIENT_CONTEXT, ActionResponse, AppAction, AppInstance, AppListResponse
from pydantic import BaseModel, ValidationError

import hassette.cli.output as cli_output
from hassette.cli.client_errors import ErrorContext, emit_usage_error
from hassette.cli.context import CLIContext
from hassette.cli.target import resolve_cli_auth_token, resolve_server_target
from hassette.config.config import HassetteConfig
from hassette.exceptions import ConfigError, FatalError

DEFAULT_TIMEOUT = 10.0

APP_GRID_PATH = "/api/telemetry/app-grid"

APPS_PATH = "/api/apps"

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


def _filter_instances(app_list: AppListResponse, app_key: str) -> list[AppInstance]:
    """Flatten the instance list for ``app_key`` out of a full app list response.

    Shared by :meth:`HassetteCLIClient._fetch_instances` and
    :meth:`HassetteCLIClient._try_fetch_instances` so the filter has one source of truth.
    """
    return [inst for app in app_list.apps if app.app_key == app_key for inst in app.instances]


def _name_for_index(instances: list[AppInstance] | None, index: int) -> str | None:
    """Return the ``instance_name`` of the instance at ``index``, or ``None`` if unknown.

    ``instances`` is ``None`` when the best-effort app list fetch failed.
    """
    if instances is None:
        return None
    return next((inst.instance_name for inst in instances if inst.index == index), None)


def query_params(**values: Any) -> dict[str, Any]:
    """Build a query-parameter dict from CLI flags, dropping every flag left unset.

    Commands share one convention: an unset flag is ``None`` and must not reach the server,
    so the endpoint applies its own default. Writing that as ``query_params(since=since,
    limit=limit)`` keeps the mapping from flag to query key on one line per command instead
    of an ``if x is not None`` block per flag.
    """
    return {key: value for key, value in values.items() if value is not None}


def parse_wire(model: type[M], data: Any) -> M:
    """Validate a server response body against a wire model, tolerating a newer server's vocabulary.

    The CLI supports talking to a newer server, so every parse goes through
    ``LENIENT_CONTEXT``: an enum value this CLI doesn't know arrives as ``UnknownValue``
    instead of failing validation. Route every wire parse through here so no call site can
    drop the context.
    """
    return model.model_validate(data, context=LENIENT_CONTEXT)


def parse_wire_list(model: type[M], raw: list[Any]) -> list[M]:
    """Validate each element of a list response with :func:`parse_wire`."""
    return [parse_wire(model, entry) for entry in raw]


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
            credential = resolve_cli_auth_token(config, target, token_file_flag=token_file_flag)
        except FatalError as exc:
            self.error_usage(str(exc))

        self.base_url = target.base_url
        self.display_url = target.display_url
        self.is_loopback = target.is_loopback
        self.errors = ErrorContext(
            json_mode=json_mode,
            debug_mode=debug_mode,
            display_url=target.display_url,
            is_loopback=target.is_loopback,
            # verify_ssl ended up False without an explicit --no-verify-ssl/--verify-ssl flag on
            # this invocation, so it came from cli.verify_ssl in config — a silent, durable
            # opt-out rather than a conscious per-invocation choice.
            insecure_from_config=not target.verify_ssl and verify_ssl_flag is None,
            credential_source_label=credential.source if credential is not None else None,
        )
        headers = {"Authorization": f"Bearer {credential.token}"} if credential is not None else {}
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
            self.errors.handle_network_error(f"Connection refused: {self.display_url} ({exc})")
        except httpx.TimeoutException:
            self.errors.handle_network_error(
                f"Request timed out after {self.timeout}s connecting to {self.display_url}"
            )
        except httpx.RequestError as exc:
            self.errors.handle_network_error(f"Network error: {exc}")
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

        is_tolerated_503 = tolerate_503 and response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        if not response.is_success and not is_tolerated_503:
            self.errors.handle_http_error(response)

        result = self._deserialize(response, model)
        self._echo_success_target_and_warnings()
        return result

    def _deserialize(self, response: httpx.Response, model: type[T]) -> Any:
        """Parse ``response`` into ``model`` (or return the raw JSON for ``dict``/``list``), exiting on failure.

        Only reached with a 2xx response or a 503 that :meth:`get` was told to tolerate.
        """
        try:
            data = response.json()
            if model is dict or model is list:
                return data
            # model is a BaseModel subclass here (dict/list handled above); pyright can't narrow T.
            return parse_wire(model, data)  # pyright: ignore[reportArgumentType]
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            # A tolerated 503 (the only non-2xx status that gets here) can carry a body that
            # isn't the expected status payload — a proxy/LB HTML error page (non-JSON) or JSON
            # of the wrong shape. Route it to the normal HTTP-error exit instead of crashing.
            # UnicodeDecodeError covers a 2xx/tolerated-503 body that isn't valid UTF-8 —
            # response.json() decodes before parsing, so malformed bytes raise this instead
            # of JSONDecodeError.
            if not response.is_success:
                self.errors.handle_http_error(response)
            # Any other successful-looking response (2xx) with an unusable body means the
            # CLI isn't actually talking to a compatible hassette instance — wrong
            # --server-url (an unrelated service or reverse proxy answering with a 200), or
            # CLI/server version skew. Surface that as a clean CLI error instead of letting
            # the parse exception propagate as a raw traceback.
            self.errors.handle_malformed_response(response, exc)

    def post(self, path: str, model: type[M]) -> M:
        """Perform a POST request to a mutation endpoint, deserialize, and handle errors.

        Mutation routes (app start/stop/reload, job trigger) take no request body or query
        params and respond with a single wire model on success.

        Args:
            model: The wire model the endpoint returns on success.

        Raises:
            SystemExit: On HTTP 4xx/5xx (code 1), network errors (code 2), or a
                successful-looking response whose body is not valid JSON or doesn't match
                ``model`` (code 1).
        """
        response = self._send("POST", path)

        if not response.is_success:
            self.errors.handle_http_error(response)

        try:
            result = parse_wire(model, response.json())
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            # Mirrors get()'s malformed-response handling above — a 2xx response we can't
            # parse into ``model`` means the same thing there does: wrong --server-url, or
            # CLI/server version skew.
            self.errors.handle_malformed_response(response, exc)

        self._echo_success_target_and_warnings()
        return result

    def post_with_instance_routing(
        self, app_key: str, action: AppAction, instance_index: int | None = None
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
            The deserialized :class:`~hassette_wire.ActionResponse`.
        """
        path = (
            f"{APPS_PATH}/{app_key}/{action}"
            if instance_index is None
            else f"{APPS_PATH}/{app_key}/instances/{instance_index}/{action}"
        )
        return self.post(path, ActionResponse)

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

    def _fetch_instances(self, app_key: str) -> list[AppInstance]:
        """Fetch the app list and return the instance list for ``app_key``."""
        app_list = self.get(APPS_PATH, AppListResponse)
        return _filter_instances(app_list, app_key)

    def _try_fetch_instances(self, app_key: str) -> list[AppInstance] | None:
        """Best-effort variant of :meth:`_fetch_instances` that never exits the process.

        ``/api/apps`` returns a 503 ``telemetry_unavailable`` problem when the
        telemetry DB is unavailable. Resolving a numeric ``--instance`` selector to its
        canonical name is a purely cosmetic lookup — the mutating start/stop/reload
        action it supports has no telemetry dependency of its own — so a telemetry
        outage must not block that action. Use this instead of :meth:`_fetch_instances`
        wherever the caller has a numeric-index fallback available; any failure here
        (network error, non-2xx status, unparseable body) returns ``None`` rather than
        calling ``sys.exit``.
        """
        try:
            response = self._client.get(APPS_PATH, timeout=self.timeout)
        except httpx.RequestError:
            return None

        if not response.is_success:
            return None

        try:
            app_list = parse_wire(AppListResponse, response.json())
        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError):
            return None

        return _filter_instances(app_list, app_key)

    def _instance_not_found(self, app_key: str, instance: str, instances: list[AppInstance]) -> NoReturn:
        names = ", ".join(repr(inst.instance_name) for inst in instances) if instances else "(none)"
        self.error_usage(f"Instance {instance!r} not found for app {app_key!r}. Available instances: {names}")

    def _find_by_name(self, instances: list[AppInstance], name: str) -> AppInstance | None:
        """Return the instance whose ``instance_name`` matches ``name`` (names are unique across the config)."""
        return next((inst for inst in instances if inst.instance_name == name), None)

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
        match = self._find_by_name(instances, instance)
        if match is not None:
            return match.index
        return self._instance_not_found(app_key, instance, instances)

    def resolve_instance_with_name(self, app_key: str, instance: str) -> tuple[int, str | None]:
        """Resolve an instance selector to its index and, when known, its canonical ``instance_name``.

        For a name selector, this always fetches the app list — there is no fallback,
        since without it there is no way to resolve which index the name refers to.

        For a digit selector, the app list name lookup is best-effort: it resolves to
        the canonical ``instance_name`` when possible so a caller building a
        human-facing message can report the same instance identity regardless of which
        selector flavor the operator used, but it tolerates the app list fetch failing
        outright (e.g. a 503 from a degraded telemetry DB — see
        :meth:`_try_fetch_instances`) the same way it already tolerates an app list with
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
            app list" — not "not found": the index is still returned as-is.

        Raises:
            SystemExit: If ``instance`` is a name that doesn't match any known instance.
        """
        try:
            index = int(instance)
        except ValueError:
            instances = self._fetch_instances(app_key)
            match = self._find_by_name(instances, instance)
            if match is not None:
                return match.index, match.instance_name
            return self._instance_not_found(app_key, instance, instances)
        else:
            # None when the app list has no entry for this index (out-of-range, or a race with
            # an app list change) or the fetch itself failed — resolved, not
            # unverified-as-in-not-found; see Returns above.
            return index, _name_for_index(self._try_fetch_instances(app_key), index)

    def resolve_instance_or_none(self, app_key: str, instance: str | None) -> int | None:
        """Resolve an instance selector, passing ``None`` through unchanged.

        Convenience wrapper for CLI commands where an unset ``--instance`` flag means
        "all instances" and should stay ``None`` rather than resolve to an index.
        """
        return None if instance is None else self.resolve_instance(app_key, instance)

    def _echo_success_target_and_warnings(self) -> None:
        """Surface the resolved non-loopback target and any TLS-verification warning once per
        invocation on the success path.

        JSON mode prints the same lines: they go to stderr, so stdout still carries exactly the
        one JSON document the command's render function writes. The target is not added as a key
        to that document because most success outputs are bare JSON arrays with no envelope to
        hold it.
        """
        if self._success_echoed:
            return
        self._success_echoed = True
        if not self.is_loopback:
            cli_output.stderr_console.print(f"[dim]Target:[/dim] {self.display_url}", highlight=False)
        if self.errors.insecure_from_config:
            self.errors.print_tls_warning()

    def error_usage(self, message: str) -> NoReturn:
        """Print a usage error and exit non-zero."""
        emit_usage_error(message, json_mode=self.json_mode)


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
    try:
        config = HassetteConfig(token=None, strict_inputs=False, **ctx.config_location_kwargs())
    except ConfigError as exc:
        emit_usage_error(f"Invalid configuration: {exc}", json_mode=ctx.json_mode)
    return HassetteCLIClient(
        config,
        json_mode=ctx.json_mode,
        debug_mode=ctx.debug_mode,
        server_url_flag=ctx.server_url,
        token_file_flag=ctx.token_file,
        verify_ssl_flag=ctx.verify_ssl,
    )

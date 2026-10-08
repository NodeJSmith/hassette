"""App management endpoints."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import TYPE_CHECKING, Any

import tomli_w
from fastapi import APIRouter, Request
from hassette_wire import (
    ActionResponse,
    AppAction,
    AppConfigResponse,
    AppListResponse,
    AppSource,
    AppSummary,
    ProblemCode,
)

from hassette.app.app_config import AppConfig
from hassette.config.classes import AppManifest
from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError
from hassette.schemas.app_config_shape import normalize_app_config
from hassette.schemas.app_snapshots import AppFullSnapshot, tally_app_statuses
from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.config_view import deref_schema, mask_app_config, mask_values, resolve_app_config_cls
from hassette.web.dependencies import HassetteDep, RuntimeDep, TelemetryDep
from hassette.web.errors import WebApiError, problem_responses
from hassette.web.mappers import app_list_response_from, app_summary_from

if TYPE_CHECKING:
    from hassette.schemas.app_snapshots import AppInstanceInfo

LOGGER = getLogger(__name__)

_VALID_APP_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$")

#: Past-tense verb for each action's success log line.
_ACTION_PAST_TENSE: dict[AppAction, str] = {"start": "Started", "stop": "Stopped", "reload": "Reloaded"}

# Keep in sync with the manifest fields on AppConfigResponse in hassette_wire/apps.py.
_MANIFEST_FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    "enabled": {
        "type": "boolean",
        "title": "Enabled",
        "description": "Whether the app is enabled.",
        "default": True,
    },
    "autostart": {
        "type": "boolean",
        "title": "Autostart",
        "description": "Whether the app starts automatically when Hassette starts.",
        "default": True,
    },
}

# Base AppConfig fields are already in the schema via class inheritance; manifest fields
# are injected by _build_app_config_view. Both groups land in the frontend's "Hassette Settings" section.
_FRAMEWORK_FIELDS: list[str] = sorted(set(AppConfig.model_fields.keys()) | set(_MANIFEST_FIELD_SCHEMAS.keys()))


# Operation-specific problem codes each shared helper below can raise. Routes compose their
# ``problem_responses(...)`` from these, so a helper that starts raising a new code changes one
# tuple here; the test-time check in tests/support/problem_codes.py catches a missed one.
APP_KEY_CODES = (ProblemCode.INVALID_APP_KEY,)
"""Codes ``_validate_app_key`` raises."""

KNOWN_APP_CODES = (ProblemCode.APP_NOT_FOUND,)
"""Codes ``_require_known_app`` raises."""

INSTANCE_INDEX_CODES = (*APP_KEY_CODES, *KNOWN_APP_CODES, ProblemCode.INSTANCE_NOT_FOUND)
"""Codes ``_require_valid_instance_index`` raises."""

STOP_ACTION_CODES = (*APP_KEY_CODES, *KNOWN_APP_CODES, ProblemCode.ACTION_IN_PROGRESS, ProblemCode.ACTION_FAILED)
"""Codes ``_run_app_action`` raises for ``stop``, which never awaits bootstrap release or checks the
``--app`` filter."""

ACTION_CODES = (*STOP_ACTION_CODES, ProblemCode.BOOTSTRAP_NOT_RELEASED, ProblemCode.APP_BLOCKED)
"""Codes ``_run_app_action`` raises for ``start`` and ``reload``."""


router = APIRouter(tags=["apps"])


def _generic_action_failure_detail(action: AppAction, app_key: str) -> str:
    """Shared fallback 500 detail for an action failure with no more specific message —
    used both when ``operation()`` itself raises and when a swallowed failure's
    ``error_message`` is empty (see ``_failed_target_instances``).
    """
    return f"Failed to {action} app {app_key!r}"


def _validate_app_key(app_key: str) -> None:
    if not _VALID_APP_KEY.match(app_key):
        raise WebApiError(ProblemCode.INVALID_APP_KEY, f"Invalid app_key: {app_key!r}")


def _orphan_app_permitted(app_key: str, hassette: HassetteDep, action: AppAction) -> bool:
    """An app with no manifest is only ever treated as "known" via its still-running instances
    for ``stop`` — ``AppLifecycleService.stop_instance()``/``_stop_app_unlocked()`` are
    deliberately permissive for an orphaned app (manifest gone from config, but the registry
    still has running instances), so the route lets the request through to match. ``start`` and
    ``reload`` are NOT extended the same permissiveness: their service-layer counterparts silently
    no-op on a missing manifest (log + return, no exception), so admitting an orphaned app there
    would turn a clear 404 into a 202-accepted request that does nothing.
    """
    return action == "stop" and bool(hassette.app_handler.registry.get_instances(app_key))


def _orphan_instance_permitted(app_key: str, index: int, hassette: HassetteDep, action: AppAction) -> bool:
    """Whether ``index`` is a still-tracked instance outside the app's current configured range.

    When an app's configured instance count shrinks while a higher-index instance is still
    running, that instance is orphaned — ``AppRegistry.prune_stale_failed_indices`` only prunes
    stale *failed* entries, never running ones, and ``build_manifest_info`` keeps reporting it in
    ``instances``. Only ``stop`` is permitted through, for the same reason as
    ``_orphan_app_permitted``: ``AppLifecycleService.stop_instance()`` matches this permissiveness,
    while ``start_instance``/``reload_instance`` silently no-op on an out-of-range index, so
    admitting them here would turn a clear 404 into a 202-accepted request that does nothing.
    """
    return action == "stop" and index in hassette.app_handler.registry.get_instances(app_key)


def _require_known_app(app_key: str, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known, or is an orphaned app that ``action`` still permits."""
    if hassette.app_handler.registry.get_manifest(app_key) is not None:
        return
    if _orphan_app_permitted(app_key, hassette, action):
        return
    raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")


def _require_valid_instance_index(app_key: str, index: int, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known and ``index`` is addressable for ``action``.

    Runs before ``_run_app_action`` so an out-of-range index returns a fast 404 without
    waiting for lock acquisition. ``AppLifecycleService`` re-validates the index itself after
    acquiring the per-app-key lock (see ``_instance_index_in_range``) — this route-level check
    is a fast path, not a substitute for that authoritative re-check under concurrent config
    changes. Uses the shared ``normalize_app_config()`` (``hassette.schemas``) rather than a
    web-local reimplementation, so this count can never drift from ``AppFactory``'s.

    Skips range validation for an orphaned app that ``action`` still permits (see
    ``_orphan_app_permitted``'s docstring for the ``stop``-only rationale), and for a
    still-tracked instance orphaned by a shrunk config (see ``_orphan_instance_permitted``).
    """
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        if _orphan_app_permitted(app_key, hassette, action):
            return
        raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")
    valid_index_count = len(normalize_app_config(manifest.app_config))
    if index < 0 or index >= valid_index_count:
        if _orphan_instance_permitted(app_key, index, hassette, action):
            return
        raise WebApiError(ProblemCode.INSTANCE_NOT_FOUND, f"Instance {index} not found for app {app_key!r}")


def _failed_target_instances(
    hassette: HassetteDep, app_key: str, instance_index: int | None
) -> dict[int, "AppInstanceInfo"]:
    """FAILED instance snapshots among the instance(s) an action targeted.

    ``start``/``reload`` (whole-app or single-instance) can fail during class loading, config
    validation, or ``on_initialize()`` without raising — ``AppFactory``/``AppLifecycleService``
    catch those failures and record them straight to the registry via ``record_failure()``
    instead. Reading the registry back after
    ``operation()`` completes, via the same ``get_failed_instance_infos()`` the registry already
    uses to re-broadcast stale failures, is how ``_run_app_action`` notices a swallowed failure.

    Scoped to ``instance_index`` when given (a single-instance action must not surface an
    unrelated sibling's failure); otherwise every instance for ``app_key``, matching a whole-app
    action's blast radius. ``stop`` never matches here: a successful stop removes its target
    entries from the registry entirely (``AppRegistry.unregister_app``), so there is nothing
    left to find FAILED.

    Not atomic with ``operation()``: the per-app-key lock in ``AppLifecycleService`` is released
    before this read, so a concurrent action against the same ``app_key`` can record or clear a
    failure between the two. A caller's response can then reflect a different, concurrent
    request's outcome rather than its own — an accepted risk for this framework's single-operator
    scope, not a guarantee this function makes.
    """
    failed = hassette.app_handler.registry.get_failed_instance_infos(app_key)
    if instance_index is None:
        return failed
    if instance_index not in failed:
        return {}
    return {instance_index: failed[instance_index]}


async def _run_app_action(
    action: AppAction,
    app_key: str,
    hassette: HassetteDep,
    request: Request,
    operation: Callable[[], Awaitable[object]],
    instance_index: int | None = None,
) -> ActionResponse:
    """Run one app lifecycle action behind the validation, error mapping, and logging every
    start/stop/reload endpoint shares.

    ``AppBootstrapNotReleasedError`` maps to a retryable 409. It is only reachable from
    start/reload — ``stop_app`` never awaits bootstrap release — so the ``stop`` endpoint
    declares no 409 response.

    ``AppBlockedError`` also maps to a non-retryable 409: the app is excluded by the ``--app``
    filter, so start/reload was rejected outright (see ``AppLifecycleService``'s blocked-app
    guards) rather than silently no-op'd — without this mapping the caller would get a 202
    "accepted" for a request nothing acted on. Also only reachable from start/reload, for the
    same reason as the bootstrap case above.

    ``action_in_progress`` (409) answers at once when another action already holds this app's
    lifecycle lock. Waiting for the lock would run the action late, after a client with a request
    timeout has already given up on it. The check is race-free because ``operation()`` reaches
    the lock without suspending: under the default ``REJECT_IF_UNRELEASED`` admission,
    ``_admit_start()`` is awaited but only does a synchronous release check, and an uncontended
    ``asyncio.Lock`` is acquired without yielding. ``AppLifecycleService``'s tests pin this.

    ``instance_index`` is echoed back on the response as-is (already validated by
    ``_require_valid_instance_index`` before this function is called) so a caller can confirm
    the server acted on the instance it intended, not just that *some* 202 came back.

    A start/reload that raises no exception can still have failed — ``AppFactory``/
    ``AppLifecycleService`` swallow class-load, config-validation, and ``on_initialize()``
    failures internally and record them to the registry instead of propagating (see
    ``_failed_target_instances``). After ``operation()`` returns cleanly, the registry is
    checked for a FAILED entry among the instance(s) targeted; if found, this maps to the same
    500 path as the ``ValueError``/``RuntimeError`` case above rather than the unconditional 202
    this function would otherwise return. A single HTTP response can only carry one failure, so
    a whole-app action with multiple failed instances surfaces the lowest-indexed one in the
    response body; every failed instance is still logged.
    """
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette, action)
    if hassette.app_handler.is_action_in_progress(app_key):
        raise WebApiError(ProblemCode.ACTION_IN_PROGRESS, f"Another action on app {app_key!r} is still running")
    await _await_operation(action, app_key, operation)
    _raise_if_target_failed(action, app_key, hassette, instance_index)
    LOGGER.info("%s app %s (source=%s)", _ACTION_PAST_TENSE[action], app_key, peer_address_or_unknown(request))
    return ActionResponse(status="accepted", app_key=app_key, action=action, instance_index=instance_index)


async def _await_operation(action: AppAction, app_key: str, operation: Callable[[], Awaitable[object]]) -> None:
    """Await ``operation`` and map the exceptions it can raise to their problem codes
    (see ``_run_app_action`` for why each mapping exists).
    """
    try:
        await operation()
    except AppBootstrapNotReleasedError as exc:
        raise WebApiError(
            ProblemCode.BOOTSTRAP_NOT_RELEASED, "App bootstrap prerequisites are not ready yet; retry later"
        ) from exc
    except AppBlockedError as exc:
        raise WebApiError(ProblemCode.APP_BLOCKED, f"App {app_key!r} is blocked by the --app filter") from exc
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to %s app %s", action, app_key, exc_info=True)
        raise WebApiError(ProblemCode.ACTION_FAILED, _generic_action_failure_detail(action, app_key)) from exc


def _raise_if_target_failed(action: AppAction, app_key: str, hassette: HassetteDep, instance_index: int | None) -> None:
    """Raise ``ACTION_FAILED`` when a cleanly-returning action left a targeted instance FAILED.

    Surfaces the lowest-indexed failure in the response and logs every failed instance (see
    ``_run_app_action`` and ``_failed_target_instances``).
    """
    failed = _failed_target_instances(hassette, app_key, instance_index)
    if not failed:
        return
    first_index = min(failed)
    detail = failed[first_index].error_message or _generic_action_failure_detail(action, app_key)
    if len(failed) > 1:
        # The response can only carry one failure — log the rest so a multi-instance
        # failure isn't silently reduced to whichever index happened to sort lowest.
        LOGGER.warning(
            "Failed to %s app %s: %d instances failed (%s); surfacing instance %s in the response",
            action,
            app_key,
            len(failed),
            ", ".join(f"{index}: {info.error_message}" for index, info in sorted(failed.items())),
            first_index,
        )
    else:
        LOGGER.warning("Failed to %s app %s (instance %s): %s", action, app_key, first_index, detail)
    raise WebApiError(ProblemCode.ACTION_FAILED, detail)


@router.get(
    "/apps",
    response_model=AppListResponse,
    responses=problem_responses(ProblemCode.TELEMETRY_UNAVAILABLE),
)
async def get_apps(runtime: RuntimeDep, telemetry: TelemetryDep) -> AppListResponse:
    """Return every persisted app, overlaid with live runtime state.

    The app spine is queried from the ``app_manifests`` DB table (``telemetry_unavailable`` on
    failure) and overlaid with live runtime state via
    ``RuntimeQueryService.overlay_manifest_rows()``, so apps with historical telemetry but
    no loaded manifest are still included.
    """
    db_rows = await telemetry.get_all_app_manifests()
    manifest_infos = runtime.overlay_manifest_rows(db_rows)

    full_snapshot = AppFullSnapshot(
        manifests=tuple(manifest_infos),
        only_apps=tuple(runtime.get_registry_only_apps()),
        total=len(manifest_infos),
        status_counts=tally_app_statuses(manifest_infos),
    )
    return app_list_response_from(full_snapshot)


@router.get(
    "/apps/{app_key}",
    response_model=AppSummary,
    responses=problem_responses(*APP_KEY_CODES, ProblemCode.TELEMETRY_UNAVAILABLE, ProblemCode.APP_NOT_FOUND),
)
async def get_app(app_key: str, runtime: RuntimeDep, telemetry: TelemetryDep) -> AppSummary:
    """Return a single persisted app, overlaid with live runtime state.

    Queries the ``app_manifests`` DB table directly instead of the in-memory registry, so an
    app with historical telemetry but no loaded manifest returns 200 instead of 404. A DB
    failure answers ``telemetry_unavailable``; a genuinely unknown ``app_key`` answers
    ``app_not_found``.
    """
    _validate_app_key(app_key)

    db_row = await telemetry.get_app_manifest(app_key)
    if db_row is None:
        raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")

    return app_summary_from(runtime.overlay_manifest_rows([db_row])[0])


@router.post(
    "/apps/{app_key}/start",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*ACTION_CODES),
)
async def start_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action("start", app_key, hassette, request, lambda: hassette.app_handler.start_app(app_key))


@router.post(
    "/apps/{app_key}/stop",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*STOP_ACTION_CODES),
)
async def stop_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action("stop", app_key, hassette, request, lambda: hassette.app_handler.stop_app(app_key))


@router.post(
    "/apps/{app_key}/reload",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*ACTION_CODES),
)
async def reload_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    # Always re-import from disk so a previously-failed app recovers once its
    # source is fixed -- without force_reload the cached failed class is reused (#1005).
    return await _run_app_action(
        "reload", app_key, hassette, request, lambda: hassette.app_handler.reload_app(app_key, force_reload=True)
    )


@router.post(
    "/apps/{app_key}/instances/{index}/start",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*INSTANCE_INDEX_CODES, *ACTION_CODES),
)
async def start_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    _require_valid_instance_index(app_key, index, hassette, "start")
    return await _run_app_action(
        "start",
        app_key,
        hassette,
        request,
        lambda: hassette.app_handler.start_instance(app_key, index),
        instance_index=index,
    )


@router.post(
    "/apps/{app_key}/instances/{index}/stop",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*INSTANCE_INDEX_CODES, *STOP_ACTION_CODES),
)
async def stop_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    _require_valid_instance_index(app_key, index, hassette, "stop")
    return await _run_app_action(
        "stop",
        app_key,
        hassette,
        request,
        lambda: hassette.app_handler.stop_instance(app_key, index),
        instance_index=index,
    )


@router.post(
    "/apps/{app_key}/instances/{index}/reload",
    status_code=202,
    response_model=ActionResponse,
    responses=problem_responses(*INSTANCE_INDEX_CODES, *ACTION_CODES),
)
async def reload_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    _require_valid_instance_index(app_key, index, hassette, "reload")
    # Always re-import from disk, matching the full app-key reload endpoint's force_reload=True
    # convention (#1005) at instance granularity.
    return await _run_app_action(
        "reload",
        app_key,
        hassette,
        request,
        lambda: hassette.app_handler.reload_instance(app_key, index, force_reload=True),
        instance_index=index,
    )


@router.get(
    "/apps/{app_key}/config",
    response_model=AppConfigResponse,
    responses=problem_responses(*APP_KEY_CODES, ProblemCode.APP_NOT_FOUND),
)
async def get_app_config(app_key: str, hassette: HassetteDep) -> AppConfigResponse:
    """Return the app configuration with schema-driven masking for the given app key.

    Secret fields are masked by type: any field declared ``SecretStr`` is replaced
    by a masked placeholder; plain ``str`` fields are never masked by name.
    The ``config_schema`` is fully inlined (no ``$ref`` nodes remain).

    Masking needs the app's config schema. It comes from the running instance when the
    app is active, otherwise from the app class if it has already been loaded. When no
    schema can be obtained (a disabled app whose class was never loaded, or a class whose
    schema generation fails), every string value is masked as a safe floor so no secret
    leaks — the masked path is the only path.
    """
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")

    app_config_cls = resolve_app_config_cls(hassette, app_key, manifest)
    if app_config_cls is not None:
        try:
            raw_schema = app_config_cls.model_json_schema()
            if not isinstance(raw_schema, dict):
                raise TypeError(f"model_json_schema() returned {type(raw_schema).__name__}, expected dict")
            config_schema, masked_config = _build_app_config_view(raw_schema, manifest.app_config)
            return _build_config_response(app_key, manifest, masked_config, config_schema)
        except Exception:
            LOGGER.warning("Failed to generate config schema for %s", app_key, exc_info=True)

    return _build_config_response(app_key, manifest, mask_app_config(None, manifest.app_config), None)


def _strip_none(obj: Any) -> Any:
    """Recursively drop None-valued keys — TOML has no null type."""
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj if v is not None]
    return obj


def _build_config_response(
    app_key: str,
    manifest: AppManifest,
    app_config: dict[str, Any] | list[dict[str, Any]],
    config_schema: dict[str, Any] | None,
) -> AppConfigResponse:
    toml_wrapper: dict[str, Any] = {"hassette": {"apps": {app_key: {"config": _strip_none(app_config)}}}}
    try:
        config_toml = tomli_w.dumps(toml_wrapper)
    except (TypeError, ValueError):
        LOGGER.warning("Failed to render TOML for %s", app_key, exc_info=True)
        config_toml = ""
    return AppConfigResponse(
        app_key=app_key,
        filename=manifest.filename,
        class_name=manifest.class_name,
        enabled=manifest.enabled,
        autostart=manifest.autostart,
        framework_fields=_FRAMEWORK_FIELDS,
        app_config=app_config,
        config_toml=config_toml,
        config_schema=config_schema,
    )


def _build_app_config_view(
    schema: dict[str, Any], app_config: dict[str, Any] | list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any] | list[dict[str, Any]]]:
    """Build the deref'd schema and masked values for a single- or multi-instance app config.

    The schema is dereferenced once and reused across every instance; only the per-instance
    masking differs. Manifest-level fields (enabled, autostart) are injected into the schema
    so the frontend can render them alongside config fields in the framework section.
    """
    plain_schema = deref_schema(schema)
    config_props = plain_schema.get("properties", {})
    enriched_schema = {**plain_schema, "properties": {**_MANIFEST_FIELD_SCHEMAS, **config_props}}
    if isinstance(app_config, list):
        return enriched_schema, [mask_values(config_props, inst) for inst in app_config]
    return enriched_schema, mask_values(config_props, app_config)


@router.get(
    "/apps/{app_key}/source",
    response_model=AppSource,
    responses=problem_responses(
        *APP_KEY_CODES,
        ProblemCode.APP_NOT_FOUND,
        ProblemCode.SOURCE_UNAVAILABLE,
        ProblemCode.PATH_TRAVERSAL,
        ProblemCode.SOURCE_NOT_FOUND,
    ),
)
async def get_app_source(app_key: str, hassette: HassetteDep) -> AppSource:
    """Return the source code of the app file for the given app key."""
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")

    # Path traversal protection: full_path must resolve within the manifest's app_dir
    try:
        resolved = manifest.full_path.resolve()
        app_dir_resolved = manifest.app_dir.resolve()
    except Exception as exc:
        LOGGER.warning("Failed to resolve paths for app %s", app_key, exc_info=True)
        raise WebApiError(ProblemCode.SOURCE_UNAVAILABLE, "Failed to resolve app path") from exc

    if not resolved.is_relative_to(app_dir_resolved):
        LOGGER.warning(
            "Path traversal attempt for app %s: %s is not within %s",
            app_key,
            resolved,
            app_dir_resolved,
        )
        raise WebApiError(ProblemCode.PATH_TRAVERSAL, "Path traversal not allowed")

    if not resolved.exists():
        raise WebApiError(ProblemCode.SOURCE_NOT_FOUND, f"Source file not found for app {app_key!r}")

    try:
        content = await asyncio.to_thread(resolved.read_text, encoding="utf-8")
    except FileNotFoundError as exc:
        raise WebApiError(ProblemCode.SOURCE_NOT_FOUND, f"Source file not found for app {app_key!r}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.warning("Failed to read source for app %s", app_key, exc_info=True)
        raise WebApiError(ProblemCode.SOURCE_UNAVAILABLE, "Failed to read app source") from exc

    return AppSource(
        app_key=app_key,
        filename=manifest.filename,
        content=content,
        line_count=len(content.splitlines()),
    )

"""App management endpoints."""

import re
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal

import tomli_w
from fastapi import APIRouter, HTTPException, Request, Response

from hassette.app.app_config import AppConfig
from hassette.config.classes import AppManifest
from hassette.exceptions import AppBootstrapNotReleasedError, TelemetryUnavailableError
from hassette.schemas.app_config_shape import normalize_app_config
from hassette.schemas.app_snapshots import AppFullSnapshot, tally_manifest_statuses
from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.config_view import deref_schema, mask_app_config, mask_values, resolve_app_config_cls
from hassette.web.dependencies import HassetteDep, RuntimeDep, TelemetryDep, db_degrades_to
from hassette.web.mappers import app_manifest_list_response_from, app_manifest_response_from, app_status_response_from
from hassette.web.models import (
    ActionResponse,
    AppConfigResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppSourceResponse,
    AppStatusResponse,
)

if TYPE_CHECKING:
    from hassette.schemas.app_snapshots import AppManifestInfo

LOGGER = getLogger(__name__)

AppAction = Literal["start", "stop", "reload"]

_VALID_APP_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$")

#: Past-tense verb for each action's success log line.
_ACTION_PAST_TENSE: dict[AppAction, str] = {"start": "Started", "stop": "Stopped", "reload": "Reloaded"}

# Keep in sync with the manifest fields on AppConfigResponse in models.py.
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


router = APIRouter(tags=["apps"])


def _validate_app_key(app_key: str) -> None:
    if not _VALID_APP_KEY.match(app_key):
        raise HTTPException(status_code=400, detail=f"Invalid app_key: {app_key!r}")


def _require_known_app(app_key: str, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known.

    ``stop`` is permissive for an orphaned app (manifest gone from config, but the registry still
    has running instances) — ``AppLifecycleService.stop_instance()``/``_stop_app_unlocked()`` are
    deliberately permissive in that case, so the route lets the request through. ``start`` and
    ``reload`` are NOT extended the same permissiveness: their service-layer counterparts silently
    no-op on a missing manifest (log + return, no exception), so admitting an orphaned app there
    would turn a clear 404 into a 202-accepted request that does nothing.
    """
    registry = hassette.app_handler.registry
    if registry.get_manifest(app_key) is not None:
        return
    if action == "stop" and registry.get_instances(app_key):
        return
    raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")


def _require_valid_instance_index(app_key: str, index: int, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known and ``index`` is within its current instance count.

    Runs before ``_run_app_action`` so an out-of-range index returns a fast 404 without
    waiting for lock acquisition. ``AppLifecycleService`` re-validates the index itself after
    acquiring the per-app-key lock (see ``_instance_index_in_range``) — this route-level check
    is a fast path, not a substitute for that authoritative re-check under concurrent config
    changes. Uses the shared ``normalize_app_config()`` (``hassette.schemas``) rather than a
    web-local reimplementation, so this count can never drift from ``AppFactory``'s.

    ``stop`` skips range validation when the manifest is gone but running instances still exist
    (orphaned app — config removed while instances are running), matching
    ``AppLifecycleService.stop_instance()``'s own permissiveness. ``start``/``reload`` do not get
    this fallback — see ``_require_known_app``'s docstring for why.
    """
    _validate_app_key(app_key)
    registry = hassette.app_handler.registry
    manifest = registry.get_manifest(app_key)
    if manifest is None:
        if action == "stop" and registry.get_instances(app_key):
            return
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")
    valid_index_count = len(normalize_app_config(manifest.app_config))
    if index < 0 or index >= valid_index_count:
        raise HTTPException(status_code=404, detail=f"Instance {index} not found for app {app_key!r}")


async def _run_app_action(
    action: AppAction,
    app_key: str,
    hassette: HassetteDep,
    request: Request,
    operation: Callable[[], Awaitable[object]],
) -> ActionResponse:
    """Run one app lifecycle action behind the validation, error mapping, and logging every
    start/stop/reload endpoint shares.

    ``AppBootstrapNotReleasedError`` maps to a retryable 409. It is only reachable from
    start/reload — ``stop_app`` never awaits bootstrap release — so the ``stop`` endpoint
    declares no 409 response.
    """
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette, action)
    try:
        await operation()
    except AppBootstrapNotReleasedError as exc:
        raise HTTPException(
            status_code=409, detail="App bootstrap prerequisites are not ready yet; retry later"
        ) from exc
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to %s app %s", action, app_key, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to {action} app") from exc
    LOGGER.info("%s app %s (source=%s)", _ACTION_PAST_TENSE[action], app_key, peer_address_or_unknown(request))
    return ActionResponse(status="accepted", app_key=app_key, action=action)


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(runtime: RuntimeDep) -> AppStatusResponse:
    return app_status_response_from(runtime.get_app_status_snapshot())


@router.get("/apps/manifests", response_model=AppManifestListResponse)
async def get_app_manifests(
    runtime: RuntimeDep, telemetry: TelemetryDep, response: Response
) -> AppManifestListResponse:
    """Return every persisted app manifest, overlaid with live runtime state.

    The app spine is queried from the ``app_manifests`` DB table (Category B — 503 via
    ``db_degrades_to`` on failure) and overlaid with live runtime state via
    ``RuntimeQueryService.overlay_manifest_rows()``, so apps with historical telemetry but
    no loaded manifest are still included. The ``recent_invocations_1h`` enrichment query
    below stays Category C (independently caught, degrading to zero while the response
    continues at 200).
    """
    manifest_infos: list[AppManifestInfo] = []
    with db_degrades_to(response):
        db_rows = await telemetry.get_all_app_manifests()
        manifest_infos = runtime.overlay_manifest_rows(db_rows)

    invocations_by_key: dict[str, int] = {}
    try:
        invocations_by_key = await telemetry.get_recent_invocations_1h_all_apps()
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch recent_invocations_1h for app manifests", exc_info=True)

    full_snapshot = AppFullSnapshot(
        manifests=manifest_infos,
        only_apps=runtime.get_registry_only_apps(),
        total=len(manifest_infos),
        status_counts=tally_manifest_statuses(manifest_infos),
    )
    manifest_list = app_manifest_list_response_from(full_snapshot)

    enriched_manifests = [
        m.model_copy(update={"recent_invocations_1h": invocations_by_key.get(m.app_key, 0)})
        for m in manifest_list.manifests
    ]
    return manifest_list.model_copy(update={"manifests": enriched_manifests})


@router.get("/apps/{app_key}/manifest", response_model=AppManifestResponse)
async def get_app_manifest(app_key: str, runtime: RuntimeDep, telemetry: TelemetryDep) -> AppManifestResponse:
    """Return the persisted manifest for a single app, overlaid with live runtime state.

    Queries the ``app_manifests`` DB table directly instead of the in-memory registry, so an
    app with historical telemetry but no loaded manifest returns 200 instead of 404. A DB
    failure and a genuinely unknown ``app_key`` are distinct failure modes (503 vs. 404) that
    don't fit the single-branch ``db_degrades_to`` shape — handled inline (Category D, see
    ``web/CLAUDE.md``).
    """
    _validate_app_key(app_key)

    try:
        db_row = await telemetry.get_app_manifest(app_key)
    except TelemetryUnavailableError as exc:
        LOGGER.warning("Failed to fetch manifest for app %s", app_key, exc_info=True)
        raise HTTPException(status_code=503, detail="Telemetry store unavailable") from exc

    if db_row is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")

    manifest_info = runtime.overlay_manifest_rows([db_row])[0]
    result = app_manifest_response_from(manifest_info)

    invocations = 0
    try:
        invocations_by_key = await telemetry.get_recent_invocations_1h_all_apps()
        invocations = invocations_by_key.get(app_key, 0)
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch recent_invocations_1h for app %s manifest", app_key, exc_info=True)

    return result.model_copy(update={"recent_invocations_1h": invocations})


@router.post(
    "/apps/{app_key}/start",
    status_code=202,
    response_model=ActionResponse,
    responses={409: {"description": "App bootstrap prerequisites are not ready yet; retry later"}},
)
async def start_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action("start", app_key, hassette, request, lambda: hassette.app_handler.start_app(app_key))


@router.post("/apps/{app_key}/stop", status_code=202, response_model=ActionResponse)
async def stop_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    return await _run_app_action("stop", app_key, hassette, request, lambda: hassette.app_handler.stop_app(app_key))


@router.post(
    "/apps/{app_key}/reload",
    status_code=202,
    response_model=ActionResponse,
    responses={409: {"description": "App bootstrap prerequisites are not ready yet; retry later"}},
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
    responses={409: {"description": "App bootstrap prerequisites are not ready yet; retry later"}},
)
async def start_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    _require_valid_instance_index(app_key, index, hassette, "start")
    return await _run_app_action(
        "start", app_key, hassette, request, lambda: hassette.app_handler.start_instance(app_key, index)
    )


@router.post("/apps/{app_key}/instances/{index}/stop", status_code=202, response_model=ActionResponse)
async def stop_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    _require_valid_instance_index(app_key, index, hassette, "stop")
    return await _run_app_action(
        "stop", app_key, hassette, request, lambda: hassette.app_handler.stop_instance(app_key, index)
    )


@router.post(
    "/apps/{app_key}/instances/{index}/reload",
    status_code=202,
    response_model=ActionResponse,
    responses={409: {"description": "App bootstrap prerequisites are not ready yet; retry later"}},
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
    )


@router.get("/apps/{app_key}/config", response_model=AppConfigResponse)
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
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")

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


@router.get("/apps/{app_key}/source", response_model=AppSourceResponse)
async def get_app_source(app_key: str, hassette: HassetteDep) -> AppSourceResponse:
    """Return the source code of the app file for the given app key."""
    _validate_app_key(app_key)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")

    # Path traversal protection: full_path must resolve within the manifest's app_dir
    try:
        resolved = manifest.full_path.resolve()
        app_dir_resolved = manifest.app_dir.resolve()
    except Exception as exc:
        LOGGER.warning("Failed to resolve paths for app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to resolve app path") from exc

    if not resolved.is_relative_to(app_dir_resolved):
        LOGGER.warning(
            "Path traversal attempt for app %s: %s is not within %s",
            app_key,
            resolved,
            app_dir_resolved,
        )
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Source file not found for app {app_key!r}")

    try:
        content = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Source file not found for app {app_key!r}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.warning("Failed to read source for app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read app source") from exc

    return AppSourceResponse(
        app_key=app_key,
        filename=manifest.filename,
        content=content,
        line_count=len(content.splitlines()),
    )

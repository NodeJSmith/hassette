"""App management endpoints."""

import re
from logging import getLogger
from typing import Any

from fastapi import APIRouter, HTTPException

from hassette.app.app_config import AppConfig
from hassette.exceptions import TelemetryUnavailableError
from hassette.web.config_view import deref_schema, mask_app_config, mask_values, resolve_app_config_cls
from hassette.web.dependencies import HassetteDep, RuntimeDep, TelemetryDep
from hassette.web.mappers import app_manifest_list_response_from, app_status_response_from
from hassette.web.models import (
    ActionResponse,
    AppConfigResponse,
    AppManifestListResponse,
    AppSourceResponse,
    AppStatusResponse,
)

LOGGER = getLogger(__name__)

_VALID_APP_KEY = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$")

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


def _require_known_app(app_key: str, hassette: HassetteDep) -> None:
    if hassette.app_handler.registry.get_manifest(app_key) is None:
        raise HTTPException(status_code=404, detail=f"App {app_key!r} not found")


@router.get("/apps", response_model=AppStatusResponse)
async def get_apps(runtime: RuntimeDep) -> AppStatusResponse:
    return app_status_response_from(runtime.get_app_status_snapshot())


@router.get("/apps/manifests", response_model=AppManifestListResponse)
async def get_app_manifests(runtime: RuntimeDep, telemetry: TelemetryDep) -> AppManifestListResponse:
    snapshot = runtime.get_all_manifests_snapshot()
    manifest_list = app_manifest_list_response_from(snapshot)

    invocations_by_key: dict[str, int] = {}
    try:
        invocations_by_key = await telemetry.get_recent_invocations_1h_all_apps()
    except TelemetryUnavailableError:
        LOGGER.warning("Failed to fetch recent_invocations_1h for app manifests", exc_info=True)

    enriched_manifests = [
        m.model_copy(update={"recent_invocations_1h": invocations_by_key.get(m.app_key, 0)})
        for m in manifest_list.manifests
    ]
    return manifest_list.model_copy(update={"manifests": enriched_manifests})


@router.post("/apps/{app_key}/start", status_code=202, response_model=ActionResponse)
async def start_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="start")


@router.post("/apps/{app_key}/stop", status_code=202, response_model=ActionResponse)
async def stop_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.stop_app(app_key)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to stop app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="stop")


@router.post("/apps/{app_key}/reload", status_code=202, response_model=ActionResponse)
async def reload_app(app_key: str, hassette: HassetteDep) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        # Always re-import from disk so a previously-failed app recovers once its
        # source is fixed -- without force_reload the cached failed class is reused (#1005).
        await hassette.app_handler.reload_app(app_key, force_reload=True)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to reload app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reload app") from exc
    return ActionResponse(status="accepted", app_key=app_key, action="reload")


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
            return AppConfigResponse(
                app_key=app_key,
                filename=manifest.filename,
                class_name=manifest.class_name,
                enabled=manifest.enabled,
                autostart=manifest.autostart,
                app_config=masked_config,
                config_schema=config_schema,
                framework_fields=_FRAMEWORK_FIELDS,
            )
        except Exception:
            LOGGER.warning("Failed to generate config schema for %s", app_key, exc_info=True)

    return AppConfigResponse(
        app_key=app_key,
        filename=manifest.filename,
        class_name=manifest.class_name,
        enabled=manifest.enabled,
        autostart=manifest.autostart,
        app_config=mask_app_config(None, manifest.app_config),
        config_schema=None,
        framework_fields=_FRAMEWORK_FIELDS,
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

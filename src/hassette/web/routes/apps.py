"""App management endpoints."""

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from logging import getLogger
from typing import Any

import tomli_w
from fastapi import APIRouter, Request
from fastapi.types import DecoratedCallable
from hassette_wire import (
    ActionResponse,
    AppAction,
    AppConfigResponse,
    AppListResponse,
    AppSource,
    AppSummary,
    InstanceOutcome,
    ProblemCode,
)

from hassette.app.app_config import AppConfig
from hassette.config.classes import AppManifest
from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError, AppRemovedError
from hassette.schemas.app_config_shape import normalize_app_config
from hassette.schemas.app_outcomes import InstanceOutcome as CoreInstanceOutcome
from hassette.schemas.app_outcomes import OutcomeResult
from hassette.schemas.app_snapshots import AppFullSnapshot, tally_app_statuses
from hassette.web.auth.trusted_proxies import peer_address_or_unknown
from hassette.web.config_view import deref_schema, mask_app_config, mask_values, resolve_app_config_cls
from hassette.web.dependencies import HassetteDep, RuntimeDep, TelemetryDep
from hassette.web.errors import WebApiError, problem_responses
from hassette.web.mappers import app_list_response_from, app_summary_from, instance_outcome_from

LOGGER = getLogger(__name__)

MAX_APP_KEY_LENGTH = 128
VALID_APP_KEY = re.compile(rf"^[a-zA-Z_][a-zA-Z0-9_.]{{0,{MAX_APP_KEY_LENGTH - 1}}}$")

#: Past-tense verb for each action's success log line.
ACTION_PAST_TENSE: dict[AppAction, str] = {"start": "Started", "stop": "Stopped", "reload": "Reloaded"}

#: ``AppManifest`` fields injected into the config view's schema (see ``_build_app_config_view``).
MANIFEST_FIELDS = ("enabled", "autostart")
MANIFEST_FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    name: schema for name, schema in AppManifest.model_json_schema()["properties"].items() if name in MANIFEST_FIELDS
}

# Base AppConfig fields are already in the schema via class inheritance; manifest fields
# are injected by _build_app_config_view. Both groups land in the frontend's "Hassette Settings" section.
FRAMEWORK_FIELDS: list[str] = sorted(set(AppConfig.model_fields.keys()) | set(MANIFEST_FIELDS))


# Operation-specific problem codes each shared helper below can raise. Routes compose their
# ``problem_responses(...)`` from these, so a helper that starts raising a new code changes one
# tuple here; the test-time check in tests/support/problem_codes.py catches a missed one.
APP_KEY_CODES = (ProblemCode.INVALID_APP_KEY,)
"""Codes ``_validate_app_key`` raises."""

KNOWN_APP_CODES = (ProblemCode.APP_NOT_FOUND,)
"""Codes ``_require_known_app`` raises."""

INSTANCE_INDEX_CODES = (
    *APP_KEY_CODES,
    *KNOWN_APP_CODES,
    ProblemCode.ACTION_IN_PROGRESS,
    ProblemCode.INSTANCE_NOT_FOUND,
)
"""Codes ``_require_valid_instance_index`` raises."""

STOP_ACTION_CODES = (
    *APP_KEY_CODES,
    *KNOWN_APP_CODES,
    ProblemCode.ACTION_IN_PROGRESS,
    ProblemCode.NEEDS_RESTART,
    ProblemCode.ACTION_FAILED,
)
"""Codes ``_run_app_action`` raises for ``stop``, which never awaits bootstrap release or checks the
``--app`` filter."""

ACTION_CODES = (*STOP_ACTION_CODES, ProblemCode.BOOTSTRAP_NOT_RELEASED, ProblemCode.APP_BLOCKED)
"""Codes ``_run_app_action`` raises for ``start`` and ``reload``."""


router = APIRouter(tags=["apps"])


def action_route(path: str, *codes: ProblemCode) -> Callable[[DecoratedCallable], DecoratedCallable]:
    """Register an app lifecycle action route: a POST answering 200 with an ``ActionResponse`` once it finishes."""
    return router.post(path, response_model=ActionResponse, responses=problem_responses(*codes))


def app_not_found(app_key: str) -> WebApiError:
    """Build the 404 error raised when no app is registered under ``app_key``."""
    return WebApiError(ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found")


def source_not_found(app_key: str) -> WebApiError:
    """Build the 404 error raised when an app's source file cannot be found."""
    return WebApiError(ProblemCode.SOURCE_NOT_FOUND, f"Source file not found for app {app_key!r}")


def _validate_app_key(app_key: str) -> None:
    if not VALID_APP_KEY.match(app_key):
        raise WebApiError(ProblemCode.INVALID_APP_KEY, f"Invalid app_key: {app_key!r}")


def _require_no_action_in_progress(app_key: str, hassette: HassetteDep) -> None:
    """Raise ``ACTION_IN_PROGRESS`` when another action holds or is queued for ``app_key``'s lock.

    Runs before any existence or instance-range check: an in-flight action can mutate the
    registry those checks read (a stop in flight unregisters each instance as its teardown ends),
    so checking existence first could turn a concurrent request into a spurious 404 instead of
    the 409 it should get.
    """
    if hassette.app_handler.is_action_in_progress(app_key):
        raise WebApiError(ProblemCode.ACTION_IN_PROGRESS, f"Another action on app {app_key!r} is still running")


def _orphan_app_permitted(app_key: str, hassette: HassetteDep, action: AppAction) -> bool:
    """Return whether an app with no manifest may proceed with ``action``.

    An app with no manifest is only ever treated as "known" via its still-running instances
    for ``stop`` — ``AppLifecycleService.stop_instance()``/``_stop_app_unlocked()`` are
    deliberately permissive for an orphaned app (manifest gone from config, but the registry
    still has running instances), so the route lets the request through to match. ``start`` and
    ``reload`` are NOT extended the same permissiveness: there is nothing to start without a
    manifest, and their service-layer counterparts raise ``AppRemovedError`` for one, so admitting an
    orphaned app there would only delay the same 404.
    """
    return action == "stop" and bool(hassette.app_handler.registry.get_instances(app_key))


def _orphan_instance_permitted(app_key: str, index: int, hassette: HassetteDep, action: AppAction) -> bool:
    """Whether ``index`` is a still-tracked instance outside the app's current configured range.

    When an app's configured instance count shrinks while a higher-index instance is still
    running, that instance is orphaned — ``AppRegistry.prune_stale_failed_indices`` only prunes
    stale *failed* entries, never running ones, and ``build_manifest_info`` keeps reporting it in
    ``instances``. Only ``stop`` is permitted through, for the same reason as
    ``_orphan_app_permitted``: ``AppLifecycleService.stop_instance()`` matches this permissiveness,
    while ``start_instance``/``reload_instance`` report an out-of-range index as a failed outcome, so
    admitting them here would turn a clear 404 into a 500.
    """
    return action == "stop" and index in hassette.app_handler.registry.get_instances(app_key)


def _require_known_app(app_key: str, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known, or is an orphaned app that ``action`` still permits."""
    if hassette.app_handler.registry.get_manifest(app_key) is not None:
        return
    if _orphan_app_permitted(app_key, hassette, action):
        return
    raise app_not_found(app_key)


def _require_manifest(app_key: str, hassette: HassetteDep) -> AppManifest:
    """Return the manifest for ``app_key``, or reject with ``app_not_found`` (orphans included)."""
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        raise app_not_found(app_key)
    return manifest


def _require_valid_instance_index(app_key: str, index: int, hassette: HassetteDep, action: AppAction) -> None:
    """Validate that ``app_key`` is known and ``index`` is addressable for ``action``.

    Runs before ``_run_app_action`` so an out-of-range index returns a fast 404 without
    waiting for lock acquisition. ``AppLifecycleService`` re-validates the index itself after
    acquiring the per-app-key lock (see ``_instance_index_in_range``) — this route-level check
    is a fast path, not a substitute for that authoritative re-check under concurrent config
    changes. Uses the shared ``normalize_app_config()`` (``hassette.schemas``) rather than a
    web-local reimplementation, so this count can never drift from ``AppFactory``'s.

    Rejects with ``action_in_progress`` before any of that, for the reason
    ``_require_no_action_in_progress`` gives.

    Skips range validation for an orphaned app that ``action`` still permits (see
    ``_orphan_app_permitted``'s docstring for the ``stop``-only rationale), and for a
    still-tracked instance orphaned by a shrunk config (see ``_orphan_instance_permitted``).
    """
    _validate_app_key(app_key)
    _require_no_action_in_progress(app_key, hassette)
    manifest = hassette.app_handler.registry.get_manifest(app_key)
    if manifest is None:
        if _orphan_app_permitted(app_key, hassette, action):
            return
        raise app_not_found(app_key)
    valid_index_count = len(normalize_app_config(manifest.app_config))
    if index < 0 or index >= valid_index_count:
        if _orphan_instance_permitted(app_key, index, hassette, action):
            return
        raise WebApiError(ProblemCode.INSTANCE_NOT_FOUND, f"Instance {index} not found for app {app_key!r}")


async def _run_app_action(
    action: AppAction,
    app_key: str,
    hassette: HassetteDep,
    request: Request,
    operation: Callable[[], Awaitable[Sequence[CoreInstanceOutcome]]],
    instance_index: int | None = None,
) -> ActionResponse:
    """Run one app lifecycle action behind the shared validation, error mapping, and logging.

    Every start/stop/reload endpoint goes through this. The action finishes before the response is
    sent, and ``operation()`` returns what it did to each instance it targeted, decided under the
    app's lifecycle lock. The worst outcome sets the status (spec 140): any ``failed`` instance gives
    500 ``action_failed``, otherwise any ``refused`` one gives 409 ``needs_restart``, otherwise 200.
    Both error bodies list every instance's outcome, as the 200 body does.

    ``AppBootstrapNotReleasedError`` maps to a retryable 409. It is only reachable from
    start/reload — ``stop_app`` never awaits bootstrap release.

    ``AppBlockedError`` also maps to a non-retryable 409: the app is excluded by the ``--app``
    filter, so start/reload was rejected outright (see ``AppLifecycleService``'s blocked-app
    guards). A reload's stop half has already run by then, so its outcomes ride along in the body.
    ``AppRemovedError`` (the manifest vanished while the action waited for the lock, or during a
    reload's stop half) maps to ``app_not_found`` the same way.

    ``action_in_progress`` (409) answers at once when another action holds or is queued for this
    app's lifecycle lock (``AppKeyLock.busy``, which stays true across a release-to-waiter
    handoff). Waiting for the lock would run the action late, after a client with a request
    timeout has already given up on it. It runs before ``_require_known_app`` for the reason
    ``_require_no_action_in_progress`` gives. The check is race-free because ``operation()`` reaches
    the lock without suspending: under the default ``REJECT_IF_UNRELEASED`` admission,
    ``_admit_start()`` is awaited but only does a synchronous release check, and an uncontended
    lock is acquired without yielding. ``AppLifecycleService``'s tests pin this.

    ``instance_index`` is echoed back on the response as-is (already validated by
    ``_require_valid_instance_index`` before this function is called) so a caller can confirm
    the server acted on the instance it intended.
    """
    _validate_app_key(app_key)
    _require_no_action_in_progress(app_key, hassette)
    _require_known_app(app_key, hassette, action)
    outcomes = await _await_operation(app_key, operation)
    wire_outcomes = [instance_outcome_from(outcome) for outcome in outcomes]
    if (code := _problem_code_for(outcomes)) is not None:
        raise WebApiError(code, action_detail(action, app_key, outcomes), outcomes=wire_outcomes)
    LOGGER.info("%s app %s (source=%s)", ACTION_PAST_TENSE[action], app_key, peer_address_or_unknown(request))
    return ActionResponse(app_key=app_key, action=action, instance_index=instance_index, outcomes=wire_outcomes)


async def _await_operation(
    app_key: str, operation: Callable[[], Awaitable[Sequence[CoreInstanceOutcome]]]
) -> Sequence[CoreInstanceOutcome]:
    """Await ``operation`` and map the exceptions it can raise to their problem codes.

    See ``_run_app_action`` for why each mapping exists.
    """
    try:
        return await operation()
    except AppBootstrapNotReleasedError as exc:
        raise WebApiError(
            ProblemCode.BOOTSTRAP_NOT_RELEASED, "App bootstrap prerequisites are not ready yet; retry later"
        ) from exc
    except AppBlockedError as exc:
        raise WebApiError(
            ProblemCode.APP_BLOCKED,
            f"App {app_key!r} is blocked by the --app filter",
            outcomes=_wire_outcomes_or_none(exc.outcomes),
        ) from exc
    except AppRemovedError as exc:
        raise WebApiError(
            ProblemCode.APP_NOT_FOUND, f"App {app_key!r} not found", outcomes=_wire_outcomes_or_none(exc.outcomes)
        ) from exc


def _wire_outcomes_or_none(outcomes: Sequence[CoreInstanceOutcome]) -> list[InstanceOutcome] | None:
    """The wire outcomes of an action rejected partway, or ``None`` when it acted on no instance."""
    return [instance_outcome_from(outcome) for outcome in outcomes] or None


def _problem_code_for(outcomes: Sequence[CoreInstanceOutcome]) -> ProblemCode | None:
    """The problem code the worst outcome calls for, or ``None`` when every instance succeeded."""
    if any(outcome.result is OutcomeResult.FAILED for outcome in outcomes):
        return ProblemCode.ACTION_FAILED
    if any(outcome.result is OutcomeResult.REFUSED for outcome in outcomes):
        return ProblemCode.NEEDS_RESTART
    return None


def action_detail(action: AppAction, app_key: str, outcomes: Sequence[CoreInstanceOutcome]) -> str:
    """The problem ``detail`` of an action that didn't succeed on every instance.

    Names each instance that didn't succeed, with its reason, after a count of what the others did
    when the action targeted more than one. The CLI and the web UI's toast show only this line, so
    it is their whole view of a partial outcome.
    """
    not_succeeded = [outcome for outcome in outcomes if outcome.result is not OutcomeResult.SUCCEEDED]
    parts = [describe_not_succeeded(outcome) for outcome in not_succeeded]
    if len(outcomes) > 1:
        done = len(outcomes) - len(not_succeeded)
        verb = ACTION_PAST_TENSE[action]
        parts.insert(0, f"{verb} {done} of {len(outcomes)} instances of app {app_key!r}")
    return "; ".join(parts)


def describe_not_succeeded(outcome: CoreInstanceOutcome) -> str:
    """One instance's part of ``action_detail``: its name and why it failed or was refused."""
    if outcome.result is OutcomeResult.REFUSED:
        return f"{outcome.instance_name!r} {outcome.reason or 'needs a hassette restart'}"
    restart = "; it needs a hassette restart" if outcome.needs_restart else ""
    return f"{outcome.instance_name!r} failed: {outcome.reason}{restart}"


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
        framework_fields=FRAMEWORK_FIELDS,
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
    enriched_schema = {**plain_schema, "properties": {**MANIFEST_FIELD_SCHEMAS, **config_props}}
    if isinstance(app_config, list):
        return enriched_schema, [mask_values(config_props, inst) for inst in app_config]
    return enriched_schema, mask_values(config_props, app_config)


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
        raise app_not_found(app_key)

    return app_summary_from(runtime.overlay_manifest_rows([db_row])[0])


@action_route("/apps/{app_key}/start", *ACTION_CODES)
async def start_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Start every instance of the app, and report what the start did to each one."""
    return await _run_app_action("start", app_key, hassette, request, lambda: hassette.app_handler.start_app(app_key))


@action_route("/apps/{app_key}/stop", *STOP_ACTION_CODES)
async def stop_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Stop every instance of the app, and report what the stop did to each one."""
    return await _run_app_action("stop", app_key, hassette, request, lambda: hassette.app_handler.stop_app(app_key))


@action_route("/apps/{app_key}/reload", *ACTION_CODES)
async def reload_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Re-import the app from disk, restart its instances, and report what the reload did to each one."""
    # Always re-import from disk so a previously-failed app recovers once its
    # source is fixed -- without force_reload the cached failed class is reused (#1005).
    return await _run_app_action(
        "reload", app_key, hassette, request, lambda: hassette.app_handler.reload_app(app_key, force_reload=True)
    )


@action_route("/apps/{app_key}/instances/{index}/start", *INSTANCE_INDEX_CODES, *ACTION_CODES)
async def start_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Start one instance of the app by index, and report what the start did to it."""
    _require_valid_instance_index(app_key, index, hassette, "start")
    return await _run_app_action(
        "start",
        app_key,
        hassette,
        request,
        lambda: hassette.app_handler.start_instance(app_key, index),
        instance_index=index,
    )


@action_route("/apps/{app_key}/instances/{index}/stop", *INSTANCE_INDEX_CODES, *STOP_ACTION_CODES)
async def stop_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Stop one instance of the app by index, and report what the stop did to it."""
    _require_valid_instance_index(app_key, index, hassette, "stop")
    return await _run_app_action(
        "stop",
        app_key,
        hassette,
        request,
        lambda: hassette.app_handler.stop_instance(app_key, index),
        instance_index=index,
    )


@action_route("/apps/{app_key}/instances/{index}/reload", *INSTANCE_INDEX_CODES, *ACTION_CODES)
async def reload_instance(app_key: str, index: int, hassette: HassetteDep, request: Request) -> ActionResponse:
    """Re-import the app from disk, restart one instance by index, and report what the reload did to it."""
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
    manifest = _require_manifest(app_key, hassette)

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
    manifest = _require_manifest(app_key, hassette)

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

    try:
        content = await asyncio.to_thread(resolved.read_text, encoding="utf-8")
    except FileNotFoundError as exc:
        raise source_not_found(app_key) from exc
    except (OSError, UnicodeDecodeError) as exc:
        LOGGER.warning("Failed to read source for app %s", app_key, exc_info=True)
        raise WebApiError(ProblemCode.SOURCE_UNAVAILABLE, "Failed to read app source") from exc

    return AppSource(
        app_key=app_key,
        filename=manifest.filename,
        content=content,
        line_count=len(content.splitlines()),
    )

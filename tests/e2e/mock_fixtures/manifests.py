"""App manifest, snapshot, and owner-resolution builders for e2e mock data."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from hassette.schemas.app_snapshots import AppManifestInfo, AppStatusSnapshot
from hassette.test_utils.web_manifest_helpers import make_app_instance_info, make_manifest, make_manifest_db_row
from hassette.types.enums import ManifestStatus, ResourceStatus
from tests.e2e.mock_fixtures.constants import (
    APP_KEY_BROKEN_APP,
    APP_KEY_DISABLED_APP,
    APP_KEY_MULTI_APP,
    APP_KEY_MY_APP,
    APP_KEY_NOSOURCE_APP,
    APP_KEY_OTHER_APP,
)

BROKEN_APP_ERROR = "Init error: bad config"
BROKEN_APP_TRACEBACK = (
    'Traceback (most recent call last):\n  File "broken_app.py", line 10, in on_initialize\n'
    '    raise ValueError("bad config")\nValueError: bad config\n'
)


def build_manifests() -> list[AppManifestInfo]:
    """Build a rich set of app manifests for e2e tests."""
    return [
        make_manifest(
            app_key=APP_KEY_MY_APP,
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            status=ManifestStatus.RUNNING,
            instance_count=1,
            instances=[make_app_instance_info(app_key=APP_KEY_MY_APP, owner_id="MyApp.MyApp[0]")],
        ),
        make_manifest(
            app_key=APP_KEY_OTHER_APP,
            class_name="OtherApp",
            display_name="Other App",
            filename="other_app.py",
            status=ManifestStatus.STOPPED,
            instance_count=0,
        ),
        make_manifest(
            app_key=APP_KEY_BROKEN_APP,
            class_name="BrokenApp",
            display_name="Broken App",
            filename="broken_app.py",
            status=ManifestStatus.FAILED,
            instance_count=1,
            instances=[
                make_app_instance_info(
                    app_key=APP_KEY_BROKEN_APP,
                    class_name="BrokenApp",
                    status=ResourceStatus.FAILED,
                    error_message=BROKEN_APP_ERROR,
                    error_traceback=BROKEN_APP_TRACEBACK,
                )
            ],
            error_message=BROKEN_APP_ERROR,
            error_traceback=BROKEN_APP_TRACEBACK,
        ),
        make_manifest(
            app_key=APP_KEY_DISABLED_APP,
            class_name="DisabledApp",
            display_name="Disabled App",
            filename="disabled_app.py",
            enabled=False,
            status=ManifestStatus.DISABLED,
            instance_count=0,
        ),
        make_manifest(
            app_key=APP_KEY_NOSOURCE_APP,
            class_name="NoSourceApp",
            display_name="No Source App",
            filename="nosource_app.py",
            status=ManifestStatus.RUNNING,
            instance_count=1,
            instances=[
                make_app_instance_info(
                    app_key=APP_KEY_NOSOURCE_APP,
                    class_name="NoSourceApp",
                    owner_id="NoSourceApp.NoSourceApp[0]",
                ),
            ],
        ),
        make_manifest(
            app_key=APP_KEY_MULTI_APP,
            class_name="MultiApp",
            display_name="Multi App",
            filename="multi_app.py",
            status=ManifestStatus.RUNNING,
            instance_count=3,
            instances=[
                make_app_instance_info(
                    app_key=APP_KEY_MULTI_APP,
                    index=index,
                    class_name="MultiApp",
                    owner_id=f"MultiApp.MultiApp[{index}]",
                )
                for index in range(3)
            ],
        ),
    ]


def build_old_snapshot() -> AppStatusSnapshot:
    """Build the legacy AppStatusSnapshot used to seed mock_hassette."""
    return AppStatusSnapshot(
        instances=[
            make_app_instance_info(app_key=APP_KEY_MY_APP, owner_id="MyApp.MyApp[0]"),
            make_app_instance_info(
                app_key=APP_KEY_NOSOURCE_APP,
                class_name="NoSourceApp",
                owner_id="NoSourceApp.NoSourceApp[0]",
            ),
            make_app_instance_info(
                app_key=APP_KEY_BROKEN_APP,
                class_name="BrokenApp",
                status=ResourceStatus.FAILED,
                error_message=BROKEN_APP_ERROR,
                error=Exception(BROKEN_APP_ERROR),
            ),
        ],
    )


def wire_app_manifest_lookups(hassette, manifests: list[AppManifestInfo]) -> None:
    """Wire manifest data for both the in-memory config-view routes and the DB-backed spine.

    - ``registry.get_manifest`` / stub ``AppManifest`` objects: needed by
      ``/apps/{key}/config`` and ``/apps/{key}/source``, which read the registry's in-memory
      manifest directly for config schema resolution and source file paths.
    - ``telemetry_query_service.get_all_app_manifests`` / ``get_app_manifest``: the DB spine
      that ``/apps/manifests`` (list) and ``/apps/{key}/manifest`` (detail) now query instead
      of the in-memory registry (design/specs/087-db-manifest-union). ``registry.manifests``
      is populated (non-empty) so ``overlay_runtime_state()`` takes the "in current config"
      branch for every seed app, and ``registry.build_manifest_info`` is wired to hand back
      each app's precomputed ``AppManifestInfo`` from ``manifests`` directly — this stub
      registry has no real running/failed/blocked app state to derive status/instances from.
    """
    # Build a stub AppManifest for each manifest — source endpoint reads full_path and app_dir.
    # We create a temp-like path pointing to a real file to avoid 404 errors in source tests;
    # for the "nosource_app" we deliberately point at a non-existent path.
    stubs: dict[str, MagicMock] = {}

    for manifest in manifests:
        stub = MagicMock()
        stub.app_key = manifest.app_key
        stub.filename = manifest.filename
        stub.class_name = manifest.class_name
        stub.enabled = manifest.enabled
        # Use a real Python file for apps that should have source, None path for nosource_app.
        if manifest.app_key == APP_KEY_NOSOURCE_APP:
            stub.full_path.resolve.return_value = Path("/nonexistent/nosource_app.py")
            stub.app_dir.resolve.return_value = Path("/nonexistent")
            stub.full_path.exists.return_value = False
        else:
            # Point at the mock_fixtures package's __init__.py so the source endpoint returns
            # real content — anchored on the package root rather than this submodule so the
            # target stays stable if the package is split further.
            real_path = (Path(__file__).parent / "__init__.py").resolve()
            stub.full_path.resolve.return_value = real_path
            stub.app_dir.resolve.return_value = real_path.parent
            stub.full_path.exists.return_value = True
        stub.app_config = {"instance_name": f"{manifest.class_name}.0", "env_prefix": manifest.app_key + "_"}
        stub.autostart = manifest.autostart
        stubs[manifest.app_key] = stub

    hassette._app_handler.registry.get_manifest.side_effect = lambda app_key: stubs.get(app_key)

    manifest_info_by_key = {manifest.app_key: manifest for manifest in manifests}

    # DB spine mocks — /apps/manifests and the dashboard grid both call
    # telemetry.get_all_app_manifests(); /apps/{key}/manifest calls telemetry.get_app_manifest().
    db_rows_by_key = {
        manifest.app_key: make_manifest_db_row(
            app_key=manifest.app_key,
            class_name=manifest.class_name,
            display_name=manifest.display_name,
            filename=manifest.filename,
            enabled=int(manifest.enabled),
            autostart=int(manifest.autostart),
            auto_loaded=int(manifest.auto_loaded),
        )
        for manifest in manifests
    }
    hassette._telemetry_query_service.get_all_app_manifests = AsyncMock(return_value=list(db_rows_by_key.values()))
    hassette._telemetry_query_service.get_app_manifest = AsyncMock(side_effect=db_rows_by_key.get)

    # overlay_runtime_state() takes the "in current config" branch only when
    # registry.manifests.get(app_key) is not None, then calls registry.build_manifest_info()
    # to derive status/instances. The value stored per key is never read (build_manifest_info
    # is stubbed below to ignore it) — its presence is what matters.
    hassette._app_handler.registry.manifests = dict(manifest_info_by_key)
    hassette._app_handler.registry.build_manifest_info.side_effect = lambda app_key, _manifest: manifest_info_by_key[
        app_key
    ]


def wire_owner_resolution(hassette) -> None:
    """Wire app instance owner resolution onto the mock app handler."""
    hassette._app_handler.registry.get_running_apps.return_value = {
        0: SimpleNamespace(unique_name="MyApp.MyApp[0]"),
    }
    hassette._app_handler.registry.get.side_effect = lambda app_key, index=0: (
        SimpleNamespace(unique_name="MyApp.MyApp[0]") if app_key == APP_KEY_MY_APP and index == 0 else None
    )

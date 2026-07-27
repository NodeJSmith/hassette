"""Unit tests for AppRegistry.overlay_runtime_state()."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.app_registry import AppRegistry, overlay_runtime_state
from hassette.test_utils import create_app_manifest
from hassette.test_utils.web_manifest_helpers import make_manifest_db_row
from hassette.types.enums import BlockReason, ResourceStatus


@pytest.fixture
def registry() -> AppRegistry:
    return AppRegistry()


@pytest.fixture
def mock_app() -> MagicMock:
    app = MagicMock()
    app.app_config.instance_name = "test_instance"
    app.class_name = "TestApp"
    app.status = ResourceStatus.RUNNING
    return app


class TestOverlayRuntimeState:
    def test_db_only_app_defaults_to_stopped(self, registry: AppRegistry) -> None:
        """A DB row with no matching registry entry is a removed/historical app."""
        rows = [make_manifest_db_row("orphan_app")]

        results = overlay_runtime_state(rows, registry)

        assert len(results) == 1
        info = results[0]
        assert info.status == "stopped"
        assert info.instance_count == 0
        assert info.instances == []
        assert info.in_current_config is False
        # Static metadata always comes from the DB row.
        assert info.class_name == "MyApp"
        assert info.display_name == "My App"
        assert info.filename == "my_app.py"
        assert info.enabled is True
        assert info.autostart is True

    def test_configured_running_app_shows_running_status(
        self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path
    ) -> None:
        manifest = create_app_manifest("running", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.register_app(manifest.app_key, 0, mock_app)

        rows = [make_manifest_db_row(manifest.app_key)]
        results = overlay_runtime_state(rows, registry)

        info = results[0]
        assert info.status == "running"
        assert info.instance_count == 1
        assert info.in_current_config is True
        # Metadata still comes from the DB row, not the in-memory manifest.
        assert info.class_name == "MyApp"
        assert info.display_name == "My App"

    def test_mixed_in_config_and_db_only_apps(self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path) -> None:
        manifest = create_app_manifest("live", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.register_app(manifest.app_key, 0, mock_app)

        rows = [make_manifest_db_row(manifest.app_key), make_manifest_db_row("removed_app")]
        results = overlay_runtime_state(rows, registry)

        assert len(results) == 2
        by_key = {info.app_key: info for info in results}
        assert by_key[manifest.app_key].status == "running"
        assert by_key[manifest.app_key].in_current_config is True
        assert by_key["removed_app"].status == "stopped"
        assert by_key["removed_app"].in_current_config is False
        assert by_key["removed_app"].instance_count == 0

    def test_status_priority_stopped_when_nothing_tracked(self, registry: AppRegistry, tmp_path: Path) -> None:
        manifest = create_app_manifest("stopped", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == "stopped"

    def test_status_priority_failed_beats_stopped(self, registry: AppRegistry, tmp_path: Path) -> None:
        manifest = create_app_manifest("failed", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.record_failure(manifest.app_key, 0, ValueError("boom"))

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == "failed"

    def test_status_priority_running_beats_failed(
        self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path
    ) -> None:
        manifest = create_app_manifest("runbeatsfail", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.register_app(manifest.app_key, 0, mock_app)
        # A different instance index failed — record_failure only pops the matching index,
        # so the running instance at index 0 stays registered alongside the failure at index 1.
        registry.record_failure(manifest.app_key, 1, ValueError("boom"))

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == "running"

    def test_status_priority_blocked_beats_running_and_failed(
        self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path
    ) -> None:
        manifest = create_app_manifest("blockedbeatsall", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})
        registry.register_app(manifest.app_key, 0, mock_app)
        registry.record_failure(manifest.app_key, 1, ValueError("boom"))
        registry.block_app(manifest.app_key, BlockReason.ONLY_APP)

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == "blocked"
        assert results[0].block_reason == BlockReason.ONLY_APP.value

    def test_status_priority_disabled_beats_everything(
        self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path
    ) -> None:
        manifest = create_app_manifest("disabledbeatsall", tmp_path, enabled=False)
        registry.set_manifests({manifest.app_key: manifest})
        registry.register_app(manifest.app_key, 0, mock_app)
        registry.record_failure(manifest.app_key, 1, ValueError("boom"))
        registry.block_app(manifest.app_key, BlockReason.ONLY_APP)

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == "disabled"

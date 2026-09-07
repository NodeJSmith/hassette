"""Unit tests for AppRegistry.overlay_runtime_state()."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.app_registry import AppRegistry, overlay_runtime_state
from hassette.types.enums import BlockReason, ResourceStatus
from tests.support.helpers import create_app_manifest
from tests.support.web_manifest_helpers import make_manifest_db_row


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

    @pytest.mark.parametrize(
        ("running", "failed", "blocked", "enabled", "expected_status", "expected_block_reason"),
        [
            (False, False, False, True, "stopped", None),
            (False, True, False, True, "failed", None),
            (True, True, False, True, "degraded", None),
            (True, True, True, True, "blocked", BlockReason.ONLY_APP.value),
            (True, True, True, False, "disabled", BlockReason.ONLY_APP.value),
        ],
        ids=[
            "nothing_tracked_is_stopped",
            "failed_beats_stopped",
            "running_plus_failed_is_degraded",
            "blocked_beats_running_and_failed",
            "disabled_beats_everything",
        ],
    )
    def test_status_priority_ladder(
        self,
        registry: AppRegistry,
        mock_app: MagicMock,
        tmp_path: Path,
        running: bool,
        failed: bool,
        blocked: bool,
        enabled: bool,
        expected_status: str,
        expected_block_reason: str | None,
    ) -> None:
        """Derived status follows a strict precedence: disabled > blocked > degraded > failed > stopped.

        Each row adds one more runtime condition on top of the row above it and asserts the
        higher-priority status wins, so the table reads as the precedence order itself. `blocked`
        stays visible in `block_reason` even once `disabled` outranks it for `status`.
        """
        manifest = create_app_manifest(expected_status, tmp_path, enabled=enabled)
        registry.set_manifests({manifest.app_key: manifest})
        if running:
            registry.register_app(manifest.app_key, 0, mock_app)
        if failed:
            # record_failure only replaces the entry at the matching index, so failing index 1
            # while index 0 stays registered is what produces a running/failed mix -- the
            # precondition for "degraded". Without a running instance, index 0 is fine.
            registry.record_failure(manifest.app_key, 1 if running else 0, ValueError("boom"))
        if blocked:
            registry.block_app(manifest.app_key, BlockReason.ONLY_APP)

        results = overlay_runtime_state([make_manifest_db_row(manifest.app_key)], registry)

        assert results[0].status == expected_status
        assert results[0].block_reason == expected_block_reason

    def test_enabled_agrees_with_status_when_db_row_is_stale(
        self, registry: AppRegistry, mock_app: MagicMock, tmp_path: Path
    ) -> None:
        """`enabled` must come from the same source as `status` — a stale DB row (from before
        a hot-reload landed) must not produce a response where `status == "disabled"` but
        `enabled is True`, a combination `build_manifest_info()` itself can never construct.
        """
        manifest = create_app_manifest("staledisabled", tmp_path, enabled=False)
        registry.set_manifests({manifest.app_key: manifest})

        # DB row still reflects the pre-reload state: enabled.
        stale_row = make_manifest_db_row(manifest.app_key, enabled=1)
        results = overlay_runtime_state([stale_row], registry)

        assert results[0].status == "disabled"
        assert results[0].enabled is False

    def test_enabled_comes_from_db_row_for_db_only_app(self, registry: AppRegistry) -> None:
        """No in-memory manifest exists for a removed app, so `enabled` has no fresher source
        than the DB row — it should reflect the DB row's value, not default to `True`.
        """
        row = make_manifest_db_row("removed_app", enabled=0)

        results = overlay_runtime_state([row], registry)

        assert results[0].in_current_config is False
        assert results[0].enabled is False

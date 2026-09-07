"""Unit tests for AppRegistry full-snapshot, blocking, autostart, and manifest-info derivation.

Covers `get_full_snapshot()` and the manifest-backed views around it. The core registration
tests and the lighter `get_snapshot()` counts live in `test_app_registry.py`.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.core.app_registry import AppRegistry
from hassette.types.enums import BlockReason, ResourceStatus

from .conftest import make_app_instance, make_manifest_obj


class TestBlockedApps:
    """Tests for blocked apps tracking."""

    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    def test_block_app(self, registry: AppRegistry) -> None:
        """Block an app and verify it is tracked."""
        registry.block_app("my_app", BlockReason.ONLY_APP)

        assert "my_app" in registry._blocked_apps
        assert registry._blocked_apps["my_app"] == BlockReason.ONLY_APP

    def test_unblock_apps(self, registry: AppRegistry) -> None:
        """Block two apps with ONLY_APP, unblock, verify both returned and dict is empty."""
        registry.block_app("app1", BlockReason.ONLY_APP)
        registry.block_app("app2", BlockReason.ONLY_APP)

        unblocked = registry.unblock_apps(BlockReason.ONLY_APP)

        assert unblocked == {"app1", "app2"}
        assert len(registry._blocked_apps) == 0

    def test_unblock_apps_returns_empty_when_none_blocked(self, registry: AppRegistry) -> None:
        """Unblocking with no blocked apps returns empty set."""
        unblocked = registry.unblock_apps(BlockReason.ONLY_APP)

        assert unblocked == set()

    def test_clear_all_clears_blocked(self, registry: AppRegistry) -> None:
        """Verify clear_all also clears _blocked_apps."""
        mock_app = MagicMock()
        registry.register_app("app1", 0, mock_app)
        registry.record_failure("app2", 0, Exception("error"))
        registry.block_app("app3", BlockReason.ONLY_APP)

        registry.clear_all()

        assert len(registry.app_keys()) == 0
        assert registry.get_snapshot().failed_count == 0
        assert len(registry._blocked_apps) == 0

    def test_is_blocked_true_for_blocked_app(self, registry: AppRegistry) -> None:
        """is_blocked() reports True for an app blocked by any reason."""
        registry.block_app("my_app", BlockReason.ONLY_APP)

        assert registry.is_blocked("my_app") is True

    def test_is_blocked_false_for_unblocked_or_unknown_app(self, registry: AppRegistry) -> None:
        """is_blocked() reports False both for an unblocked known app and an unknown one."""
        registry.block_app("other_app", BlockReason.ONLY_APP)

        assert registry.is_blocked("my_app") is False

    def test_is_blocked_false_after_unblock(self, registry: AppRegistry) -> None:
        """is_blocked() reflects unblock_apps() — the authoritative check AppLifecycleService
        relies on must never lag the registry's own blocked-set state.
        """
        registry.block_app("my_app", BlockReason.ONLY_APP)
        registry.unblock_apps(BlockReason.ONLY_APP)

        assert registry.is_blocked("my_app") is False


class TestAppRegistryGetFullSnapshot:
    """Unit tests for get_full_snapshot() status derivation."""

    def make_registry(self) -> AppRegistry:
        return AppRegistry()

    def test_empty_manifests(self) -> None:
        reg = self.make_registry()
        snap = reg.get_full_snapshot()
        assert snap.total == 0
        assert snap.manifests == []

    def test_running_app(self) -> None:
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app")})
        reg.register_app("my_app", 0, make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        assert snap.total == 1
        assert snap.status_counts["running"] == 1
        assert snap.manifests[0].status == "running"
        assert snap.manifests[0].instance_count == 1

    def test_stopped_app(self) -> None:
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app")})
        # No instances registered — status is "stopped"
        snap = reg.get_full_snapshot()
        assert snap.status_counts["stopped"] == 1
        assert snap.manifests[0].status == "stopped"

    def test_failed_app(self) -> None:
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app")})
        reg.record_failure("my_app", 0, RuntimeError("init error"))
        snap = reg.get_full_snapshot()
        assert snap.status_counts["failed"] == 1
        assert snap.manifests[0].status == "failed"
        assert snap.manifests[0].error_message == "init error"

    def test_disabled_app(self) -> None:
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app", enabled=False)})
        snap = reg.get_full_snapshot()
        assert snap.status_counts["disabled"] == 1
        assert snap.manifests[0].status == "disabled"

    def test_blocked_app(self) -> None:
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app")})
        reg.block_app("my_app", BlockReason.ONLY_APP)
        snap = reg.get_full_snapshot()
        assert snap.status_counts["blocked"] == 1
        assert snap.manifests[0].status == "blocked"
        assert snap.manifests[0].block_reason == "only_app"

    def test_mixed_states(self) -> None:
        reg = self.make_registry()
        reg.set_manifests(
            {
                "running_app": make_manifest_obj("running_app"),
                "stopped_app": make_manifest_obj("stopped_app"),
                "failed_app": make_manifest_obj("failed_app"),
                "disabled_app": make_manifest_obj("disabled_app", enabled=False),
                "blocked_app": make_manifest_obj("blocked_app"),
            }
        )
        reg.register_app("running_app", 0, make_app_instance("running_app"))
        reg.record_failure("failed_app", 0, ValueError("bad config"))
        reg.block_app("blocked_app", BlockReason.ONLY_APP)

        snap = reg.get_full_snapshot()
        assert snap.total == 5
        assert snap.status_counts["running"] == 1
        assert snap.status_counts["stopped"] == 1
        assert snap.status_counts["failed"] == 1
        assert snap.status_counts["disabled"] == 1
        assert snap.status_counts["blocked"] == 1

        statuses = {m.app_key: m.status for m in snap.manifests}
        assert statuses["running_app"] == "running"
        assert statuses["stopped_app"] == "stopped"
        assert statuses["failed_app"] == "failed"
        assert statuses["disabled_app"] == "disabled"
        assert statuses["blocked_app"] == "blocked"

    def test_get_full_snapshot_running_failed_stopped_counts_and_manifest_info(self) -> None:
        """Characterization pin: manifests + running + failed instances produce correct
        running/failed/stopped counts on ``AppFullSnapshot`` and correct per-manifest
        ``AppManifestInfo`` fields (status, instance_count, error_message).
        """
        reg = self.make_registry()
        reg.set_manifests(
            {
                "running_app": make_manifest_obj("running_app"),
                "failed_app": make_manifest_obj("failed_app"),
                "stopped_app": make_manifest_obj("stopped_app"),
            }
        )
        reg.register_app("running_app", 0, make_app_instance("running_app"))
        error = RuntimeError("startup failed")
        reg.record_failure("failed_app", 0, error)

        snap = reg.get_full_snapshot()

        assert snap.total == 3
        assert snap.status_counts["running"] == 1
        assert snap.status_counts["failed"] == 1
        assert snap.status_counts["stopped"] == 1
        assert snap.status_counts["disabled"] == 0
        assert snap.status_counts["blocked"] == 0

        by_key = {m.app_key: m for m in snap.manifests}

        running_info = by_key["running_app"]
        assert running_info.status == "running"
        assert running_info.instance_count == 1
        assert running_info.instances[0].status == ResourceStatus.RUNNING

        failed_info = by_key["failed_app"]
        assert failed_info.status == "failed"
        assert failed_info.instance_count == 1
        assert failed_info.error_message == "startup failed"
        assert failed_info.instances[0].status == ResourceStatus.FAILED

        stopped_info = by_key["stopped_app"]
        assert stopped_info.status == "stopped"
        # A configured-but-never-started instance is a synthetic STOPPED placeholder, not
        # omitted — instance_count reflects the configured count, not the tracked count.
        assert stopped_info.instance_count == 1
        assert stopped_info.instances[0].status == ResourceStatus.STOPPED

    def test_disabled_takes_priority_over_running(self) -> None:
        """Even if an app has running instances, disabled=False should win."""
        reg = self.make_registry()
        reg.set_manifests({"my_app": make_manifest_obj("my_app", enabled=False)})
        reg.register_app("my_app", 0, make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        # Disabled takes priority
        assert snap.manifests[0].status == "disabled"

    def test_snapshot_includes_autostart_field(self) -> None:
        """get_full_snapshot() sets autostart on each AppManifestInfo from the manifest."""
        reg = self.make_registry()
        reg.set_manifests(
            {
                "auto_app": make_manifest_obj("auto_app", autostart=True),
                "manual_app": make_manifest_obj("manual_app", autostart=False),
            }
        )
        snap = reg.get_full_snapshot()
        by_key = {m.app_key: m for m in snap.manifests}
        assert by_key["auto_app"].autostart is True
        assert by_key["manual_app"].autostart is False

    def test_autostart_false_enabled_app_has_status_stopped(self) -> None:
        """An enabled+autostart=false manifest with no instances derives status 'stopped', not 'disabled'."""
        reg = self.make_registry()
        reg.set_manifests({"manual_app": make_manifest_obj("manual_app", enabled=True, autostart=False)})
        snap = reg.get_full_snapshot()
        assert snap.manifests[0].status == "stopped"
        assert snap.manifests[0].autostart is False
        assert snap.status_counts["stopped"] == 1
        assert snap.status_counts["disabled"] == 0


class TestAppRegistryAutostart:
    """Tests for autostart_manifests property."""

    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    def make_manifest(  # factory-local: returns SimpleNamespace for registry tests
        self, enabled: bool = True, autostart: bool = True
    ) -> SimpleNamespace:
        return SimpleNamespace(enabled=enabled, autostart=autostart)

    def test_autostart_manifests_includes_autostart_true(self, registry: AppRegistry) -> None:
        """autostart_manifests includes enabled+autostart=true manifests."""
        registry.set_manifests(
            {
                "auto_app": self.make_manifest(enabled=True, autostart=True),
            }
        )
        result = registry.autostart_manifests
        assert "auto_app" in result

    def test_autostart_manifests_excludes_autostart_false(self, registry: AppRegistry) -> None:
        """autostart_manifests excludes manifests where autostart=false."""
        registry.set_manifests(
            {
                "auto_app": self.make_manifest(enabled=True, autostart=True),
                "manual_app": self.make_manifest(enabled=True, autostart=False),
            }
        )
        result = registry.autostart_manifests
        assert "auto_app" in result
        assert "manual_app" not in result

    def test_autostart_manifests_excludes_disabled(self, registry: AppRegistry) -> None:
        """autostart_manifests also excludes disabled apps (via active_manifests)."""
        registry.set_manifests(
            {
                "disabled_app": self.make_manifest(enabled=False, autostart=True),
            }
        )
        result = registry.autostart_manifests
        assert "disabled_app" not in result

    def test_active_manifests_still_includes_autostart_false(self, registry: AppRegistry) -> None:
        """active_manifests is unchanged — it still includes autostart=false enabled apps."""
        registry.set_manifests(
            {
                "manual_app": self.make_manifest(enabled=True, autostart=False),
            }
        )
        assert "manual_app" in registry.active_manifests

    def test_enabled_manifests_still_includes_autostart_false(self, registry: AppRegistry) -> None:
        """enabled_manifests is unchanged — it still includes autostart=false enabled apps."""
        registry.set_manifests(
            {
                "manual_app": self.make_manifest(enabled=True, autostart=False),
            }
        )
        assert "manual_app" in registry.enabled_manifests


class TestBuildManifestInfoStatusDerivation:
    """Characterization pins for ``build_manifest_info()``'s status derivation.

    Covers the 6-value priority chain (disabled > blocked > degraded > running > failed >
    stopped), including the ``degraded`` value derived when an app_key has at least one
    running and at least one failed instance.
    """

    @pytest.fixture
    def registry(self) -> AppRegistry:
        return AppRegistry()

    def test_disabled(self, registry: AppRegistry) -> None:
        manifest = make_manifest_obj("my_app", enabled=False)
        info = registry.build_manifest_info("my_app", manifest)
        assert info.status == "disabled"

    def test_blocked(self, registry: AppRegistry) -> None:
        manifest = make_manifest_obj("my_app")
        registry.block_app("my_app", BlockReason.ONLY_APP)
        info = registry.build_manifest_info("my_app", manifest)
        assert info.status == "blocked"
        assert info.block_reason == "only_app"

    def test_running(self, registry: AppRegistry) -> None:
        manifest = make_manifest_obj("my_app")
        registry.register_app("my_app", 0, make_app_instance("my_app"))
        info = registry.build_manifest_info("my_app", manifest)
        assert info.status == "running"
        assert info.instance_count == 1

    def test_failed(self, registry: AppRegistry) -> None:
        manifest = make_manifest_obj("my_app")
        registry.record_failure("my_app", 0, ValueError("bad config"))
        info = registry.build_manifest_info("my_app", manifest)
        assert info.status == "failed"
        assert info.error_message == "bad config"

    def test_stopped(self, registry: AppRegistry) -> None:
        """No instances registered and no failures recorded — status is 'stopped', but the
        configured instance still appears as a STOPPED placeholder (not omitted).
        """
        manifest = make_manifest_obj("my_app")
        info = registry.build_manifest_info("my_app", manifest)
        assert info.status == "stopped"
        assert info.instance_count == 1
        assert info.instances[0].status == ResourceStatus.STOPPED

    def test_stopped_instance_kept_addressable_in_multi_instance_app(self, registry: AppRegistry) -> None:
        """One instance of a 2-instance app is stopped (never started or independently
        stopped) — it still appears in ``instances`` as a STOPPED placeholder, keeping
        ``instance_count`` stable at the configured count and the instance resolvable by
        name/index, instead of vanishing once it's no longer tracked in the registry.
        """
        manifest = make_manifest_obj("my_app", app_config=[{"instance_name": "office"}, {"instance_name": "kitchen"}])
        registry.register_app("my_app", 0, make_app_instance("my_app", 0))
        # index 1 ("kitchen") is configured but never started/tracked.

        info = registry.build_manifest_info("my_app", manifest)

        assert info.instance_count == 2
        assert info.status == "running"
        by_index = {inst.index: inst for inst in info.instances}
        assert by_index[0].status == ResourceStatus.RUNNING
        assert by_index[1].status == ResourceStatus.STOPPED
        assert by_index[1].instance_name == "kitchen"

    def test_orphaned_running_instance_beyond_configured_range_is_not_dropped(self, registry: AppRegistry) -> None:
        """A running instance at an index outside the current config range (config shrunk
        while it's running) is still included — the configured range and the tracked
        entries are unioned, never a plain ``range(configured_count)``, so a live orphan is
        never silently dropped from view.
        """
        manifest = make_manifest_obj("my_app", app_config=[{"instance_name": "only"}])
        registry.register_app("my_app", 0, make_app_instance("my_app", 0))
        registry.register_app("my_app", 1, make_app_instance("my_app", 1))  # orphaned, index >= configured_count

        info = registry.build_manifest_info("my_app", manifest)

        assert info.instance_count == 2
        indices = {inst.index for inst in info.instances}
        assert indices == {0, 1}

    def test_degraded_when_running_and_failed_coexist(self, registry: AppRegistry) -> None:
        """3 instances registered, index 0 fails — status is 'degraded'."""
        manifest = make_manifest_obj("my_app")
        registry.register_app("my_app", 0, make_app_instance("my_app", 0))
        registry.register_app("my_app", 1, make_app_instance("my_app", 1))
        registry.register_app("my_app", 2, make_app_instance("my_app", 2))

        registry.record_failure("my_app", 0, ValueError("bad config"))

        info = registry.build_manifest_info("my_app", manifest)

        assert info.status == "degraded"
        assert info.instance_count == 3

    def test_all_failed_is_failed_not_degraded(self, registry: AppRegistry) -> None:
        """All instances failed (none running) — status is 'failed', not 'degraded'."""
        manifest = make_manifest_obj("my_app")
        registry.record_failure("my_app", 0, ValueError("bad config"))
        registry.record_failure("my_app", 1, ValueError("also bad"))

        info = registry.build_manifest_info("my_app", manifest)

        assert info.status == "failed"

    @pytest.mark.parametrize(
        ("app_config", "expected_name"),
        [
            ([{"instance_name": "custom_instance"}], "custom_instance"),
            (None, "MyApp.0"),
            ([{"instance_name": None}], "MyApp.0"),
            ([{"instance_name": False}], "MyApp.0"),
            ([{"instance_name": 0}], "MyApp.0"),
            ([{"instance_name": ""}], "MyApp.0"),
        ],
        ids=["configured_name", "no_app_config", "null", "false", "zero", "empty_string"],
    )
    def test_failed_instance_name_resolution(
        self, registry: AppRegistry, app_config: list[dict] | None, expected_name: str
    ) -> None:
        """A failed entry's instance_name comes from the manifest's configured app_config when
        that value is a usable string, and otherwise falls back to ``ClassName.index``.

        The fallback has to cover more than a missing key. A non-string or empty configured
        ``instance_name`` -- an explicit ``null`` in the user's config, say -- must not flow
        through as-is: ``AppInstanceInfo.instance_name`` is a required ``str``, and the eventual
        ``AppInstanceResponse`` Pydantic mapping would raise a validation error on anything else,
        turning the status endpoint into a 500.
        """
        manifest = make_manifest_obj("my_app", app_config=app_config)
        registry.record_failure("my_app", 0, ValueError("boom"))

        info = registry.build_manifest_info("my_app", manifest)

        assert info.instances[0].instance_name == expected_name

    def test_failed_instance_name_falls_back_when_no_manifest(self, registry: AppRegistry) -> None:
        """When no manifest is tracked for the app_key, fall back to ``Unknown.index``."""
        registry.record_failure("orphan_app", 0, ValueError("boom"))

        snapshot = registry.get_snapshot()

        assert snapshot.instances[0].instance_name == "Unknown.0"
        assert snapshot.instances[0].class_name == "Unknown"

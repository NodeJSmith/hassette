"""Unit tests for AppRegistry's needs-restart record and the resolver every per-index reader goes through."""

import pytest
from hassette_wire import AppStatus, ResourceStatus

from hassette.core.app_registry import AppRegistry, overlay_runtime_state
from tests.support.web_manifest_helpers import make_manifest_db_row

from .conftest import make_app_instance, make_manifest_obj


def flag(registry: AppRegistry, app_key: str = "my_app", index: int = 0, reason: str = "work still running") -> bool:
    return registry.flag_needs_restart(
        app_key, index, instance_name=f"{app_key}.{index}", class_name="MyApp", reason=reason, pending_tasks=("t1",)
    )


@pytest.fixture
def registry() -> AppRegistry:
    registry = AppRegistry()
    registry.set_manifests({"my_app": make_manifest_obj("my_app")})
    return registry


class TestRecord:
    def test_survives_unregister_and_a_later_failure_entry(self, registry: AppRegistry) -> None:
        registry.register_app("my_app", 0, make_app_instance("my_app"))
        flag(registry)

        registry.unregister_app("my_app", 0)
        registry.record_failure("my_app", 0, ValueError("boom"))
        registry.unregister_app("my_app")

        info = registry.resolve_instance_info("my_app", 0)
        assert info is not None
        assert info.status == ResourceStatus.FAILED
        assert info.needs_restart is not None
        assert info.needs_restart.pending_tasks == ("t1",)
        assert info.needs_restart.flagged_at is not None

    def test_survives_pruning_and_config_changes(self, registry: AppRegistry) -> None:
        registry.record_failure("my_app", 3, ValueError("boom"))
        flag(registry, index=3)

        registry.prune_stale_failed_indices("my_app", valid_index_count=1)
        registry.set_manifests({})

        assert registry.resolve_instance_info("my_app", 3) is not None

    def test_first_record_stands(self, registry: AppRegistry) -> None:
        assert flag(registry, reason="first") is True
        assert flag(registry, reason="second") is False

        info = registry.resolve_instance_info("my_app", 0)
        assert info is not None
        assert info.needs_restart is not None
        assert info.needs_restart.reason == "first"

    def test_clear_all_clears_it(self, registry: AppRegistry) -> None:
        flag(registry)

        registry.clear_all()

        assert registry.resolve_instance_info("my_app", 0) is None


class TestResolver:
    def test_record_wins_over_a_live_entry(self, registry: AppRegistry) -> None:
        registry.register_app("my_app", 0, make_app_instance("my_app"))
        flag(registry)

        info = registry.resolve_instance_info("my_app", 0)

        assert info is not None
        assert info.status == ResourceStatus.FAILED
        assert info.error_message == "work still running"

    def test_entry_error_message_is_kept_over_the_reason(self, registry: AppRegistry) -> None:
        registry.record_failure("my_app", 0, TimeoutError("stop timed out"))
        flag(registry)

        info = registry.resolve_instance_info("my_app", 0)

        assert info is not None
        assert info.error_message == "stop timed out"

    def test_without_a_record_the_entry_is_returned_as_is(self, registry: AppRegistry) -> None:
        registry.register_app("my_app", 0, make_app_instance("my_app"))

        info = registry.resolve_instance_info("my_app", 0)

        assert info is not None
        assert info.status == ResourceStatus.RUNNING
        assert info.needs_restart is None


class TestReaders:
    def test_snapshot_counts_a_flagged_instance_as_failed(self, registry: AppRegistry) -> None:
        registry.register_app("my_app", 0, make_app_instance("my_app"))
        flag(registry)

        snapshot = registry.get_snapshot()

        assert snapshot.running_count == 0
        assert snapshot.failed_count == 1

    def test_failed_instance_infos_include_a_record_only_index(self, registry: AppRegistry) -> None:
        flag(registry)

        assert set(registry.get_failed_instance_infos("my_app")) == {0}

    def test_manifest_info_is_failed_with_a_count(self, registry: AppRegistry) -> None:
        flag(registry)

        info = registry.build_manifest_info("my_app", registry.manifests["my_app"])

        assert info.status == AppStatus.FAILED
        assert info.needs_restart_count == 1
        assert info.instances[0].needs_restart is not None

    def test_manifest_info_is_degraded_with_a_running_sibling(self, registry: AppRegistry) -> None:
        registry.set_manifests(
            {"my_app": make_manifest_obj("my_app", app_config=[{"instance_name": "a"}, {"instance_name": "b"}])}
        )
        registry.register_app("my_app", 0, make_app_instance("my_app"))
        flag(registry, index=1)

        info = registry.build_manifest_info("my_app", registry.manifests["my_app"])

        assert info.status == AppStatus.DEGRADED

    def test_app_removed_from_config_still_renders_its_flagged_instance(self, registry: AppRegistry) -> None:
        flag(registry, app_key="gone_app")

        [info] = overlay_runtime_state([make_manifest_db_row("gone_app")], registry)

        assert info.status == AppStatus.FAILED
        assert info.in_current_config is False
        assert info.needs_restart_count == 1
        assert [i.instance_name for i in info.instances] == ["gone_app.0"]
        assert info.class_name == "MyApp"

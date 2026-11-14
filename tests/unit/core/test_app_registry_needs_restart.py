"""Unit tests for AppRegistry's needs-restart flag on a FAILED entry, and the readers that report it."""

import pytest
from hassette_wire import AppStatus, ResourceStatus

from hassette.core.app_registry import AppRegistry, overlay_runtime_state
from tests.support.app_registry_helpers import seed_failed, seed_running
from tests.support.web_manifest_helpers import make_manifest_db_row

from .conftest import make_app_instance, make_manifest_obj


def flag(
    registry: AppRegistry,
    app_key: str = "my_app",
    name: str = "my_app",
    reason: str = "work still running",
    error: Exception | None = None,
) -> None:
    seed_failed(registry, app_key, name, error, needs_restart=reason, pending_tasks=("t1",))


@pytest.fixture
def registry() -> AppRegistry:
    registry = AppRegistry()
    registry.set_manifests({"my_app": make_manifest_obj("my_app")})
    return registry


class TestFlag:
    def test_flag_sits_on_the_failed_entry(self, registry: AppRegistry) -> None:
        seed_running(registry, "my_app", make_app_instance("my_app"))
        flag(registry)

        info = registry.resolve_instance_info("my_app", "my_app")
        assert info is not None
        assert info.status == ResourceStatus.FAILED
        assert info.needs_restart is not None
        assert info.needs_restart.pending_tasks == ("t1",)
        assert info.needs_restart.flagged_at is not None
        assert registry.get("my_app", "my_app") is None

    def test_survives_the_stale_failed_prune_and_config_changes(self, registry: AppRegistry) -> None:
        flag(registry, name="removed")

        assert registry.stale_failed_names("my_app", ["my_app"]) == []
        registry.set_manifests({})

        assert registry.resolve_instance_info("my_app", "removed") is not None

    def test_clear_all_clears_it(self, registry: AppRegistry) -> None:
        flag(registry)

        registry.clear_all()

        assert registry.resolve_instance_info("my_app", "my_app") is None

    def test_the_failure_error_message_is_reported(self, registry: AppRegistry) -> None:
        flag(registry, error=TimeoutError("stop timed out"))

        info = registry.resolve_instance_info("my_app", "my_app")

        assert info is not None
        assert info.error_message == "stop timed out"

    def test_without_a_flag_the_entry_is_returned_as_is(self, registry: AppRegistry) -> None:
        seed_running(registry, "my_app", make_app_instance("my_app"))

        info = registry.resolve_instance_info("my_app", "my_app")

        assert info is not None
        assert info.status == ResourceStatus.RUNNING
        assert info.needs_restart is None


class TestReaders:
    def test_snapshot_counts_a_flagged_instance_as_failed(self, registry: AppRegistry) -> None:
        seed_running(registry, "my_app", make_app_instance("my_app"))
        flag(registry)

        snapshot = registry.get_snapshot()

        assert snapshot.running_count == 0
        assert snapshot.failed_count == 1

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
        seed_running(registry, "my_app", make_app_instance("my_app"))
        flag(registry, name="b")

        info = registry.build_manifest_info("my_app", registry.manifests["my_app"])

        assert info.status == AppStatus.DEGRADED

    def test_app_removed_from_config_still_renders_its_flagged_instance(self, registry: AppRegistry) -> None:
        flag(registry, app_key="gone_app", name="gone_app")

        [info] = overlay_runtime_state([make_manifest_db_row("gone_app")], registry)

        assert info.status == AppStatus.FAILED
        assert info.in_current_config is False
        assert info.needs_restart_count == 1
        assert [i.instance_name for i in info.instances] == ["gone_app"]
        assert info.class_name == "MyApp"


class TestRefusalReason:
    def test_none_when_the_name_is_not_flagged(self, registry: AppRegistry) -> None:
        flag(registry, name="other")

        assert registry.refusal_reason("my_app", "my_app") is None

    def test_says_a_restart_is_needed_with_the_flag_time_and_reason(self, registry: AppRegistry) -> None:
        flag(registry, reason="task t1 still pending")
        flag_info = registry.get_needs_restart("my_app", "my_app")
        assert flag_info is not None

        refusal = registry.refusal_reason("my_app", "my_app")

        assert refusal == f"needs a hassette restart (flagged at {flag_info.flagged_at}: task t1 still pending)"


class TestDisplayNames:
    def test_a_flagged_name_outside_the_config_keeps_its_name(self, registry: AppRegistry) -> None:
        flag(registry, name="gone")

        assert "gone" in registry.display_names("my_app")

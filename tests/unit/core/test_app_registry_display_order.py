"""AppRegistry's name keys and the display order derived from them."""

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_registry import AppRegistry
from tests.support.app_registry_helpers import seed_failed, seed_running

from .conftest import make_app_instance, make_manifest_obj

APP_KEY = "my_app"


def manifest_with(*names: str):
    return make_manifest_obj(APP_KEY, app_config=[{"instance_name": name} for name in names])


@pytest.fixture
def registry() -> AppRegistry:
    registry = AppRegistry()
    registry.set_manifests({APP_KEY: manifest_with("upstairs", "downstairs")})
    return registry


class TestDisplayOrder:
    def test_configured_names_in_config_order_then_orphans_sorted_by_name(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "zed"))
        seed_failed(registry, APP_KEY, "attic", ValueError("boom"))

        assert registry.display_names(APP_KEY) == ["upstairs", "downstairs", "attic", "zed"]

    def test_a_flagged_name_outside_the_config_is_an_orphan_too(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "attic", needs_restart="work still running")

        assert registry.display_names(APP_KEY) == ["upstairs", "downstairs", "attic"]

    def test_a_reorder_changes_the_order_and_nothing_tracked(self, registry: AppRegistry) -> None:
        app = make_app_instance(APP_KEY, "downstairs")
        seed_running(registry, APP_KEY, app)

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        assert registry.get(APP_KEY, "downstairs") is app
        assert registry.display_names(APP_KEY) == ["downstairs", "upstairs"]

    def test_an_orphans_position_shifts_when_the_config_changes(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "attic"))
        assert registry.display_names(APP_KEY) == ["upstairs", "downstairs", "attic"]

        registry.set_manifests({APP_KEY: manifest_with("upstairs")})

        assert registry.display_names(APP_KEY) == ["upstairs", "attic"]

    def test_an_app_without_a_manifest_orders_only_its_tracked_names(self) -> None:
        registry = AppRegistry()
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "zed"))
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "attic"))

        assert registry.display_names(APP_KEY) == ["attic", "zed"]


class TestGet:
    def test_no_name_returns_the_first_running_instance_in_config_order(self, registry: AppRegistry) -> None:
        downstairs = make_app_instance(APP_KEY, "downstairs")
        seed_running(registry, APP_KEY, downstairs)
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "attic"))
        seed_failed(registry, APP_KEY, "upstairs", ValueError("boom"))

        assert registry.get(APP_KEY) is downstairs

    def test_no_name_with_nothing_running_returns_none(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "upstairs", ValueError("boom"))

        assert registry.get(APP_KEY) is None


class TestPerInstanceRecordsFollowTheName:
    def test_a_flag_follows_its_instance_across_a_reorder(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "downstairs", needs_restart="work still running")

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        assert registry.refusal_reason(APP_KEY, "downstairs") is not None
        assert registry.refusal_reason(APP_KEY, "upstairs") is None
        info = registry.resolve_instance_info(APP_KEY, "downstairs")
        assert info is not None
        assert info.status == ResourceStatus.FAILED

    def test_a_failure_follows_its_instance_across_a_reorder(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "downstairs", ValueError("boom"))

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        statuses = {info.instance_name: info.status for info in registry.get_full_snapshot().manifests[0].instances}
        assert statuses == {"downstairs": ResourceStatus.FAILED, "upstairs": ResourceStatus.STOPPED}

    def test_a_renamed_flagged_instance_passes_the_gate_while_the_old_name_stays_failed(
        self, registry: AppRegistry
    ) -> None:
        seed_failed(registry, APP_KEY, "downstairs", needs_restart="work still running")

        registry.set_manifests({APP_KEY: manifest_with("upstairs", "basement")})

        assert registry.refusal_reason(APP_KEY, "basement") is None
        old = registry.resolve_instance_info(APP_KEY, "downstairs")
        assert old is not None
        assert (old.status, old.in_current_config) == (ResourceStatus.FAILED, False)

    def test_a_flagged_name_moved_to_another_app_passes_the_gate(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "downstairs", needs_restart="work still running")

        assert registry.refusal_reason("other_app", "downstairs") is None

    def test_prune_keeps_configured_names_and_running_orphans(self, registry: AppRegistry) -> None:
        seed_failed(registry, APP_KEY, "upstairs", ValueError("boom"))
        seed_failed(registry, APP_KEY, "attic", ValueError("boom"))
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY, "zed"))

        assert registry.stale_failed_names(APP_KEY, ["upstairs", "downstairs"]) == ["attic"]

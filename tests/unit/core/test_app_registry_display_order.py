"""AppRegistry's name keys and the display order derived from them for index-addressed readers."""

import pytest
from hassette_wire import ResourceStatus

from hassette.config.classes import instance_name_reason
from hassette.core.app_registry import AppRegistry

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
        registry.register_app(APP_KEY, "zed", make_app_instance(APP_KEY))
        registry.record_failure(APP_KEY, "attic", ValueError("boom"))

        assert registry.display_indices(APP_KEY) == {"upstairs": 0, "downstairs": 1, "attic": 2, "zed": 3}

    def test_a_flagged_name_outside_the_config_is_an_orphan_too(self, registry: AppRegistry) -> None:
        registry.flag_needs_restart(APP_KEY, "attic", class_name="MyApp", reason="work still running")

        assert registry.display_indices(APP_KEY)["attic"] == 2

    def test_a_reorder_changes_the_index_and_nothing_tracked(self, registry: AppRegistry) -> None:
        app = make_app_instance(APP_KEY)
        registry.register_app(APP_KEY, "downstairs", app)

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        assert registry.get(APP_KEY, "downstairs") is app
        info = registry.resolve_instance_info(APP_KEY, "downstairs")
        assert info is not None
        assert info.index == 0

    def test_an_orphans_index_shifts_when_the_config_changes(self, registry: AppRegistry) -> None:
        registry.register_app(APP_KEY, "attic", make_app_instance(APP_KEY))
        assert registry.display_index(APP_KEY, "attic") == 2

        registry.set_manifests({APP_KEY: manifest_with("upstairs")})

        assert registry.display_index(APP_KEY, "attic") == 1

    def test_a_name_the_app_lacks_sorts_after_all_it_has(self, registry: AppRegistry) -> None:
        assert registry.display_index(APP_KEY, "gone") == 2


class TestIndexLookup:
    def test_every_display_index_resolves_to_exactly_one_name(self, registry: AppRegistry) -> None:
        registry.register_app(APP_KEY, "attic", make_app_instance(APP_KEY))

        names = [registry.instance_name(APP_KEY, index) for index in range(3)]

        assert names == ["upstairs", "downstairs", "attic"]

    @pytest.mark.parametrize("index", [-1, 2, 9])
    def test_an_index_with_no_name_gets_a_label_that_is_never_a_valid_name(
        self, registry: AppRegistry, index: int
    ) -> None:
        assert instance_name_reason(registry.instance_name(APP_KEY, index)) is not None

    def test_an_app_without_a_manifest_orders_only_its_tracked_names(self) -> None:
        registry = AppRegistry()
        registry.register_app(APP_KEY, "zed", make_app_instance(APP_KEY))
        registry.register_app(APP_KEY, "attic", make_app_instance(APP_KEY))

        assert registry.instance_name(APP_KEY, 0) == "attic"
        assert instance_name_reason(registry.instance_name(APP_KEY, 2)) is not None


class TestGet:
    def test_no_name_returns_the_first_running_instance_in_config_order(self, registry: AppRegistry) -> None:
        downstairs = make_app_instance(APP_KEY)
        registry.register_app(APP_KEY, "downstairs", downstairs)
        registry.register_app(APP_KEY, "attic", make_app_instance(APP_KEY))
        registry.record_failure(APP_KEY, "upstairs", ValueError("boom"))

        assert registry.get(APP_KEY) is downstairs

    def test_no_name_with_nothing_running_returns_none(self, registry: AppRegistry) -> None:
        registry.record_failure(APP_KEY, "upstairs", ValueError("boom"))

        assert registry.get(APP_KEY) is None


class TestPerInstanceRecordsFollowTheName:
    def test_a_flag_follows_its_instance_across_a_reorder(self, registry: AppRegistry) -> None:
        registry.flag_needs_restart(APP_KEY, "downstairs", class_name="MyApp", reason="work still running")

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        assert registry.refusal_reason(APP_KEY, "downstairs") is not None
        assert registry.refusal_reason(APP_KEY, "upstairs") is None
        info = registry.resolve_instance_info(APP_KEY, "downstairs")
        assert info is not None
        assert (info.index, info.status) == (0, ResourceStatus.FAILED)

    def test_a_failure_follows_its_instance_across_a_reorder(self, registry: AppRegistry) -> None:
        registry.record_failure(APP_KEY, "downstairs", ValueError("boom"))

        registry.set_manifests({APP_KEY: manifest_with("downstairs", "upstairs")})

        statuses = {info.instance_name: info.status for info in registry.get_full_snapshot().manifests[0].instances}
        assert statuses == {"downstairs": ResourceStatus.FAILED, "upstairs": ResourceStatus.STOPPED}

    def test_a_renamed_flagged_instance_passes_the_gate_while_the_old_name_stays_failed(
        self, registry: AppRegistry
    ) -> None:
        registry.flag_needs_restart(APP_KEY, "downstairs", class_name="MyApp", reason="work still running")

        registry.set_manifests({APP_KEY: manifest_with("upstairs", "basement")})

        assert registry.refusal_reason(APP_KEY, "basement") is None
        old = registry.resolve_instance_info(APP_KEY, "downstairs")
        assert old is not None
        assert (old.status, old.in_current_config) == (ResourceStatus.FAILED, False)

    def test_a_flagged_name_moved_to_another_app_passes_the_gate(self, registry: AppRegistry) -> None:
        registry.flag_needs_restart(APP_KEY, "downstairs", class_name="MyApp", reason="work still running")

        assert registry.refusal_reason("other_app", "downstairs") is None

    def test_prune_keeps_configured_names_and_running_orphans(self, registry: AppRegistry) -> None:
        registry.record_failure(APP_KEY, "upstairs", ValueError("boom"))
        registry.record_failure(APP_KEY, "attic", ValueError("boom"))
        registry.register_app(APP_KEY, "zed", make_app_instance(APP_KEY))

        pruned = registry.prune_stale_failed(APP_KEY, ["upstairs", "downstairs"])

        assert list(pruned) == ["attic"]
        assert set(registry.get_instances(APP_KEY)) == {"upstairs", "zed"}

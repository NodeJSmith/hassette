"""``AppRegistry.status_revision`` and ``app_status``: the ordering and the rollup every status surface shares."""

import time

import pytest
from hassette_wire import AppStatus, ResourceStatus

from hassette.core.app_registry import AppRegistry, overlay_runtime_state
from hassette.schemas.app_snapshots import NeedsRestartInfo
from hassette.types.enums import BlockReason
from hassette.utils import date_utils
from tests.support.app_registry_helpers import seed_failed, seed_running
from tests.support.web_manifest_helpers import make_manifest_db_row

from .conftest import make_app_instance, make_manifest_obj

APP_KEY = "my_app"


@pytest.fixture
def registry() -> AppRegistry:
    registry = AppRegistry()
    registry.set_manifests({APP_KEY: make_manifest_obj(APP_KEY)})
    return registry


def seed_instances(registry: AppRegistry, statuses: list[ResourceStatus]) -> None:
    """Track one instance per status, named ``i0``, ``i1``, ..."""
    for index, status in enumerate(statuses):
        name = f"i{index}"
        if status is ResourceStatus.FAILED:
            seed_failed(registry, APP_KEY, name)
        else:
            seed_running(registry, APP_KEY, make_app_instance(APP_KEY, name), status)


class TestStatusRevision:
    def test_seeded_from_the_wall_clock_in_microseconds(self) -> None:
        before = time.time_ns() // 1_000
        registry = AppRegistry()
        assert before <= registry.status_revision <= time.time_ns() // 1_000

    def test_each_change_bumps_by_one_and_carries_the_new_revision(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY), ResourceStatus.STARTING)
        start = registry.status_revision

        change = registry.set_status(APP_KEY, APP_KEY, ResourceStatus.RUNNING)

        assert change is not None
        assert change.status_revision == start + 1 == registry.status_revision

    def test_a_write_that_changes_nothing_does_not_bump(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY))
        start = registry.status_revision

        assert registry.set_status(APP_KEY, APP_KEY, ResourceStatus.RUNNING) is None
        assert registry.set_status("unknown", "x", ResourceStatus.RUNNING) is None
        assert registry.status_revision == start

    def test_registration_onto_a_missing_entry_bumps_without_a_change(self, registry: AppRegistry) -> None:
        start = registry.status_revision

        change = registry.set_status(APP_KEY, APP_KEY, ResourceStatus.NOT_STARTED, app=make_app_instance(APP_KEY))

        assert change is None
        assert registry.status_revision == start + 1

    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(lambda r: r.block_app(APP_KEY, BlockReason.ONLY_APP), id="block_app"),
            pytest.param(lambda r: r.set_manifests(dict(r.manifests)), id="set_manifests"),
        ],
    )
    def test_writes_without_a_change_that_alter_status_bump(self, registry: AppRegistry, write) -> None:
        start = registry.status_revision
        write(registry)
        assert registry.status_revision == start + 1

    def test_unblock_bumps_only_when_something_was_blocked(self, registry: AppRegistry) -> None:
        start = registry.status_revision
        registry.unblock_apps(BlockReason.ONLY_APP)
        assert registry.status_revision == start

        registry.block_app(APP_KEY, BlockReason.ONLY_APP)
        registry.unblock_apps(BlockReason.ONLY_APP)
        assert registry.status_revision == start + 2

    def test_debug_capture_and_only_apps_do_not_bump(self, registry: AppRegistry) -> None:
        start = registry.status_revision
        registry.set_debug_capture(APP_KEY, [APP_KEY], enabled=True)
        registry.set_only_apps([APP_KEY])
        assert registry.status_revision == start

    def test_snapshots_carry_the_revision_they_were_read_at(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY))
        infos = overlay_runtime_state([make_manifest_db_row(APP_KEY), make_manifest_db_row("gone")], registry)
        assert [info.status_revision for info in infos] == [registry.status_revision] * 2
        assert registry.get_full_snapshot().manifests[0].status_revision == registry.status_revision


class TestAppStatusRollup:
    @pytest.mark.parametrize(
        ("statuses", "expected"),
        [
            pytest.param([], AppStatus.STOPPED, id="nothing-tracked"),
            pytest.param([ResourceStatus.NOT_STARTED], AppStatus.STARTING, id="registered"),
            pytest.param([ResourceStatus.STARTING], AppStatus.STARTING, id="single-initializing"),
            pytest.param([ResourceStatus.RUNNING] * 3 + [ResourceStatus.STARTING], AppStatus.STARTING, id="restarting"),
            pytest.param([ResourceStatus.RUNNING] * 3 + [ResourceStatus.STOPPING], AppStatus.STOPPING, id="stopping"),
            pytest.param(
                [ResourceStatus.STARTING, ResourceStatus.STOPPING], AppStatus.STARTING, id="starting-over-stopping"
            ),
            pytest.param([ResourceStatus.RUNNING] * 2, AppStatus.RUNNING, id="all-running"),
            pytest.param([ResourceStatus.FAILED], AppStatus.FAILED, id="failed"),
            pytest.param([ResourceStatus.FAILED, ResourceStatus.STARTING], AppStatus.DEGRADED, id="failed-and-live"),
            pytest.param([ResourceStatus.FAILED, ResourceStatus.RUNNING], AppStatus.DEGRADED, id="degraded"),
        ],
    )
    def test_follows_one_ordered_list(
        self, registry: AppRegistry, statuses: list[ResourceStatus], expected: AppStatus
    ) -> None:
        seed_instances(registry, statuses)
        assert registry.app_status(APP_KEY) is expected

    def test_config_states_win(self, registry: AppRegistry) -> None:
        seed_instances(registry, [ResourceStatus.FAILED])
        registry.block_app(APP_KEY, BlockReason.ONLY_APP)
        assert registry.app_status(APP_KEY) is AppStatus.BLOCKED
        registry.set_manifests({APP_KEY: make_manifest_obj(APP_KEY, enabled=False)})
        assert registry.app_status(APP_KEY) is AppStatus.DISABLED


class TestDeltaAgreesWithSnapshot:
    """A change's ``app_status`` equals the snapshot ``status`` read at the same revision."""

    def assert_agrees(self, registry: AppRegistry, app_key: str, write) -> None:
        change = write()
        assert change is not None
        (info,) = overlay_runtime_state([make_manifest_db_row(app_key)], registry)
        assert info.status_revision == change.status_revision
        assert info.status == change.app_status

    def test_removed_app_with_a_flagged_instance(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY))
        registry.set_manifests({})
        self.assert_agrees(
            registry,
            APP_KEY,
            lambda: registry.set_status(
                APP_KEY,
                APP_KEY,
                ResourceStatus.FAILED,
                error=RuntimeError("stuck"),
                needs_restart=NeedsRestartInfo(reason="stuck", pending_tasks=(), flagged_at=date_utils.now()),
            ),
        )

    def test_disabled_app(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY))
        registry.set_manifests({APP_KEY: make_manifest_obj(APP_KEY, enabled=False)})
        self.assert_agrees(registry, APP_KEY, lambda: registry.set_status(APP_KEY, APP_KEY, ResourceStatus.STOPPING))

    def test_blocked_app(self, registry: AppRegistry) -> None:
        seed_running(registry, APP_KEY, make_app_instance(APP_KEY))
        registry.block_app(APP_KEY, BlockReason.ONLY_APP)
        self.assert_agrees(registry, APP_KEY, lambda: registry.set_status(APP_KEY, APP_KEY, ResourceStatus.STOPPED))

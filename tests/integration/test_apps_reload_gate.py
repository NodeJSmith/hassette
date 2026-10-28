"""Reload decisions under the app-key lock, and the needs-restart replacement gate (#3110)."""

import asyncio
import typing
from copy import deepcopy
from pathlib import Path

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.testing import HassetteHarness, wait_for
from tests.support.factories import make_change_set
from tests.support.outcomes import AnyIndexOutcomes

TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"
MULTI_INSTANCE_APP_KEY = "multi_instance"


def multi_instance_manifest(app_config: list[dict] | None = None) -> AppManifest:
    """The ``multi_instance`` test app's manifest; two instances, ``alpha`` and ``beta``, unless given a config."""
    if app_config is None:
        app_config = [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
    return AppManifest(
        app_key=MULTI_INSTANCE_APP_KEY,
        filename="multi_instance_app.py",
        class_name="MultiInstanceApp",
        app_dir=TEST_APPS_PATH,
        app_config=app_config,
        enabled=True,
        display_name="Multi Instance",
        full_path=TEST_APPS_PATH / "multi_instance_app.py",
    )


@pytest.fixture
async def lifecycle(hassette_with_app_handler: HassetteHarness) -> typing.AsyncIterator[AppLifecycleService]:
    """A fresh ``AppLifecycleService`` over its own ``AppRegistry`` on the module's harness ``Hassette``.

    Its own registry keeps the ``multi_instance`` manifest off the harness's ``AppHandler`` registry.
    """
    service = AppLifecycleService(hassette_with_app_handler.hassette, parent=None, registry=AppRegistry())
    try:
        yield service
    finally:
        await service.shutdown_all()


class TestReloadLockAndNeedsRestartGate:
    async def test_config_change_waiting_behind_a_stop_does_not_recreate_what_the_stop_removed(
        self, lifecycle: AppLifecycleService
    ) -> None:
        """A config change that waits on the app-key lock decides its plan after the lock is free (#1689 gap 1).

        An autostart=false app is running; a stop holds its lock when a config change to one instance arrives.
        Once the stop ends the app is dormant, so a decision made under the lock skips it. A plan made before
        the wait would recreate the stopped instance.
        """
        app_key = MULTI_INSTANCE_APP_KEY
        manifest = multi_instance_manifest()
        manifest.autostart = False
        lifecycle.set_apps_configs({app_key: manifest})
        await lifecycle.start_app(app_key)
        assert len(lifecycle.registry.get_running_apps(app_key)) == 2, "Precondition: both instances running"

        original_config = deepcopy(lifecycle.registry.manifests)
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "a", "instance_name": "alpha"},
            {"value": "changed", "instance_name": "beta"},
        ]

        lock = lifecycle._get_app_key_lock(app_key)
        async with lock:  # stands in for an in-flight HTTP stop, which holds the lock across its body
            task = asyncio.create_task(
                lifecycle.apply_changes(
                    make_change_set(reload_apps={app_key}), original_config, lifecycle.registry.manifests
                )
            )
            await wait_for(lambda: lock.claims == 2, desc="config change queued on the app-key lock")
            await lifecycle._stop_app_unlocked(app_key, outcomes=AnyIndexOutcomes())
        await asyncio.wait_for(task, timeout=2)

        assert lifecycle.registry.get_running_apps(app_key) == {}

    async def test_batch_reload_does_not_create_over_an_index_its_own_stop_flagged(
        self, lifecycle: AppLifecycleService
    ) -> None:
        """A stop earlier in the same batch that flags its index blocks that index's replacement (#1689 gap 2).

        The sibling's replacement is still created, and the flagged index keeps reporting FAILED with its
        needs-restart record.
        """
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)

        original_config = deepcopy(lifecycle.registry.manifests)
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "a2", "instance_name": "alpha"},
            {"value": "b2", "instance_name": "beta"},
        ]

        orig_stop = lifecycle._stop_instance_unlocked

        async def stop_that_leaves_work_running(app_key: str, index: int) -> None:
            await orig_stop(app_key, index)
            if index == 1:
                lifecycle.registry.flag_needs_restart(
                    app_key, 1, instance_name="beta", class_name="MultiInstanceApp", reason="work still running"
                )

        lifecycle._stop_instance_unlocked = stop_that_leaves_work_running

        await lifecycle.apply_changes(
            make_change_set(reload_apps={app_key}), original_config, lifecycle.registry.manifests
        )

        instance0 = lifecycle.registry.get(app_key, 0)
        assert instance0 is not None
        assert instance0.app_config.model_dump()["value"] == "a2"
        assert lifecycle.registry.get(app_key, 1) is None
        info = lifecycle.registry.resolve_instance_info(app_key, 1)
        assert info is not None
        assert info.needs_restart is not None

    async def test_reload_app_recreates_siblings_but_not_a_flagged_index(
        self,
        lifecycle: AppLifecycleService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A whole-app reload skips a flagged index with one refusal ERROR and recreates its siblings.

        The reload's create goes through ``AppFactory.create_instances``.
        """
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)
        await lifecycle.stop_instance(app_key, 0)
        lifecycle.registry.flag_needs_restart(
            app_key, 0, instance_name="alpha", class_name="MultiInstanceApp", reason="work still running"
        )
        instance1_before = lifecycle.registry.get(app_key, 1)

        await lifecycle.reload_app(app_key)

        assert lifecycle.registry.get(app_key, 0) is None
        instance1_after = lifecycle.registry.get(app_key, 1)
        assert instance1_after is not None
        assert instance1_after is not instance1_before
        refusal = lifecycle.registry.refusal_for(app_key, 0)
        assert refusal is not None
        refusals = [r for r in caplog.records if r.getMessage() == refusal]
        assert len(refusals) == 1

    async def test_start_app_with_every_index_flagged_starts_nothing_and_does_not_raise(
        self,
        lifecycle: AppLifecycleService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A start with nothing left to create logs one refusal per index and leaves both flags in place."""
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        for idx, name in enumerate(("alpha", "beta")):
            lifecycle.registry.flag_needs_restart(
                app_key, idx, instance_name=name, class_name="MultiInstanceApp", reason="work still running"
            )

        await lifecycle.start_app(app_key)

        assert lifecycle.registry.get_running_apps(app_key) == {}
        infos = lifecycle.registry.resolve_instance_infos(app_key)
        assert sorted(infos) == [0, 1]
        assert all(info.needs_restart is not None for info in infos.values())
        expected = {lifecycle.registry.refusal_for(app_key, idx) for idx in (0, 1)}
        assert None not in expected
        assert {r.getMessage() for r in caplog.records if r.levelname == "ERROR"} == expected

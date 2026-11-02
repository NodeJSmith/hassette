import asyncio
import typing
from copy import deepcopy
from pathlib import Path

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_lifecycle_common import ActionOutcomes
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.testing import HassetteHarness, wait_for
from tests.support.factories import make_change_set, make_job_registration, make_listener_registration
from tests.support.helpers import noop

TEST_APPS_PATH = Path(__file__).parent.parent / "data" / "apps"


class TestPerInstanceSelectiveRestart:
    """Selective per-instance restart on config change and via reload_instance() (#796).

    Uses a fresh ``AppLifecycleService`` + ``AppRegistry`` so the ``multi_instance`` manifest
    here never touches the shared ``hassette_with_app_handler`` registry that ``TestApps``
    asserts app counts against. Reuses that fixture's already-wired ``Hassette`` instance
    (rather than constructing a second ``HassetteHarness``) because only one harness may hold
    the process-global Hassette context at a time — see ``real_db_lifecycle`` below.
    """

    MULTI_INSTANCE_APP_KEY = "multi_instance"

    def _make_manifest(self, app_config: list[dict]) -> AppManifest:
        return AppManifest(
            app_key=self.MULTI_INSTANCE_APP_KEY,
            filename="multi_instance_app.py",
            class_name="MultiInstanceApp",
            app_dir=TEST_APPS_PATH,
            app_config=app_config,
            enabled=True,
            display_name="Multi Instance",
            full_path=TEST_APPS_PATH / "multi_instance_app.py",
        )

    @pytest.fixture
    async def real_db_lifecycle(
        self, hassette_with_app_handler: HassetteHarness
    ) -> typing.AsyncIterator[tuple[AppLifecycleService, CommandExecutor, DatabaseService]]:
        """A fresh ``AppLifecycleService`` wired to a real DB-backed ``CommandExecutor``.

        ``HassetteHarness`` normally mocks ``CommandExecutor`` entirely for bus/scheduler/
        app-handler components (see ``harness.py`` ``_start_bus``/``_start_scheduler``/
        ``_start_app_handler``) — listener/job registrations never persist to a real
        database. Swapping in a real ``CommandExecutor`` (backed by a real ``DatabaseService``)
        on the module-scoped harness's ``Hassette`` lets ``reconcile_app_registrations()`` run
        its real reconciliation SQL, which the DB-survival test below needs to observe. The
        swap is restored in the ``finally`` block so ``TestApps``'s other tests keep seeing the
        harness's normal mock.

        A second, independently-constructed ``HassetteHarness``/``Hassette`` was tried first but
        collides on the process-global Hassette context (``context.set_global_hassette``) while
        this module's own ``hassette_with_app_handler`` harness is still alive — only one
        ``Hassette`` instance may hold that context at a time.
        """
        hassette = hassette_with_app_handler.hassette
        original_command_executor = hassette._command_executor
        original_database_service = hassette._database_service

        db_service = DatabaseService(hassette, parent=hassette)
        await db_service.on_initialize()
        hassette._database_service = db_service

        executor = CommandExecutor(hassette, parent=hassette)
        await executor.on_initialize()
        hassette._command_executor = executor

        registry = AppRegistry()
        lifecycle = AppLifecycleService(hassette, parent=None, registry=registry)

        try:
            yield lifecycle, executor, db_service
        finally:
            await lifecycle.shutdown_all()
            await executor.on_shutdown()
            await db_service.on_shutdown()
            hassette._command_executor = original_command_executor
            hassette._database_service = original_database_service

    async def test_selective_restart_reloads_only_changed_instance(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """A config change to one instance restarts only that instance.

        The sibling instance keeps running undisturbed — same object identity, not recreated.
        """
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        original_manifest = self._make_manifest(
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
        )
        lifecycle.set_apps_configs({app_key: original_manifest})

        await lifecycle.start_app(app_key)

        alpha_before = lifecycle.registry.get(app_key, "alpha")
        beta_before = lifecycle.registry.get(app_key, "beta")
        assert alpha_before is not None, "Precondition: alpha should be running"
        assert beta_before is not None, "Precondition: beta should be running"

        original_config = deepcopy(lifecycle.registry.manifests)
        # Mutate beta's config only — alpha's dict stays identical.
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "a", "instance_name": "alpha"},
            {"value": "changed", "instance_name": "beta"},
        ]

        changes = make_change_set(reload_apps={app_key})
        await lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests)

        await wait_for(
            lambda: (
                (beta := lifecycle.registry.get(app_key, "beta")) is not None
                and beta.app_config.model_dump()["value"] == "changed"
            ),
            desc="beta reloaded with updated config",
        )

        alpha_after = lifecycle.registry.get(app_key, "alpha")
        beta_after = lifecycle.registry.get(app_key, "beta")
        assert alpha_after is alpha_before, (
            "alpha should not have been recreated — sibling instance must stay undisturbed"
        )
        assert beta_after is not None
        assert beta_after is not beta_before, "beta should have been recreated"
        assert beta_after.app_config.model_dump()["value"] == "changed", "beta should reflect the new config"

    async def apply_config(self, lifecycle: AppLifecycleService, app_config: list[dict]) -> None:
        """Change the multi-instance app's config and apply it the way a live config reload does."""
        original_config = deepcopy(lifecycle.registry.manifests)
        lifecycle.registry.manifests[self.MULTI_INSTANCE_APP_KEY].app_config = app_config
        changes = make_change_set(reload_apps={self.MULTI_INSTANCE_APP_KEY})
        await lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests)

    async def test_reorder_restarts_nothing_and_each_instance_keeps_its_records(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """Moving config blocks leaves every instance running; only the display order changes."""
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        alpha_config = {"value": "a", "instance_name": "alpha"}
        beta_config = {"value": "b", "instance_name": "beta"}
        lifecycle.set_apps_configs({app_key: self._make_manifest([alpha_config, beta_config])})
        await lifecycle.start_app(app_key)
        alpha, beta = lifecycle.registry.get(app_key, "alpha"), lifecycle.registry.get(app_key, "beta")
        assert alpha is not None
        assert beta is not None

        await self.apply_config(lifecycle, [beta_config, alpha_config])

        assert lifecycle.registry.get(app_key, "alpha") is alpha
        assert lifecycle.registry.get(app_key, "beta") is beta
        manifest = lifecycle.registry.get_manifest(app_key)
        assert manifest is not None
        instances = lifecycle.registry.build_manifest_info(app_key, manifest).instances
        assert [info.instance_name for info in instances] == ["beta", "alpha"]

    async def test_adding_an_instance_starts_only_it(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        alpha_config = {"value": "a", "instance_name": "alpha"}
        lifecycle.set_apps_configs({app_key: self._make_manifest([alpha_config])})
        await lifecycle.start_app(app_key)
        alpha = lifecycle.registry.get(app_key, "alpha")

        await self.apply_config(lifecycle, [{"value": "b", "instance_name": "beta"}, alpha_config])

        assert lifecycle.registry.get(app_key, "alpha") is alpha, "the unchanged sibling keeps running"
        beta = lifecycle.registry.get(app_key, "beta")
        assert beta is not None

    @pytest.mark.parametrize(
        "new_config",
        [
            [{"value": "a", "instance_name": "alpha"}],
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta_renamed"}],
        ],
        ids=["removed", "renamed"],
    )
    async def test_a_name_leaving_the_config_stops_alone_and_its_rows_retire_at_the_reload(
        self,
        real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService],
        monkeypatch: pytest.MonkeyPatch,
        new_config: list[dict],
    ) -> None:
        """Its listener stops counting as active without waiting for a retention cycle, and is not deleted."""
        lifecycle, executor, db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs(
            {
                app_key: self._make_manifest(
                    [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
                )
            }
        )
        await lifecycle.start_app(app_key)
        alpha = lifecycle.registry.get(app_key, "alpha")
        registered = {
            name: await executor.register_listener(
                make_listener_registration(instance_name=name, app_key=app_key, name=f"{name}_l")
            )
            for name in ("alpha", "beta")
        }
        # This lifecycle's registry isn't the harness's, so the database reads this app's live set from it.
        monkeypatch.setattr(
            db_service,
            "live_instances",
            lambda: (
                [(app_key, config["instance_name"]) for config in new_config]
                + [(app_key, name) for name in lifecycle.registry.get_running_apps(app_key)]
            ),
        )

        await self.apply_config(lifecycle, new_config)

        assert lifecycle.registry.get(app_key, "alpha") is alpha, "the unchanged sibling keeps running"
        assert lifecycle.registry.get(app_key, "beta") is None

        async def retired_at(listener_id: int | None) -> float | None:
            cursor = await db_service.db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
            row = await cursor.fetchone()
            assert row is not None, "retiring must keep the row, so a queued execution keeps its parent"
            return row["retired_at"]

        beta_retired_at = None
        for _ in range(200):
            beta_retired_at = await retired_at(registered["beta"])
            if beta_retired_at is not None:
                break
            await asyncio.sleep(0.01)
        assert beta_retired_at is not None
        assert await retired_at(registered["alpha"]) is None

    async def test_reload_instance_preserves_sibling_db_rows(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """reload_instance() must not retire sibling instances' listener/job DB rows.

        MultiInstanceApp registers no listeners/jobs of its own, so both instances' rows are
        seeded directly via CommandExecutor to give the reconciliation SQL real rows to scope
        against. After reload_instance(app_key, "beta"), alpha's rows must survive unchanged
        while beta's stale rows (nothing "live" after its own reload) are cleaned up —
        proving the reconciliation SQL is scoped by instance_name, not just app_key.
        """
        lifecycle, executor, db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        manifest = self._make_manifest(
            [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
        )
        lifecycle.set_apps_configs({app_key: manifest})

        await lifecycle.start_app(app_key)
        assert lifecycle.registry.get(app_key, "alpha") is not None, "Precondition: alpha should be running"
        assert lifecycle.registry.get(app_key, "beta") is not None, "Precondition: beta should be running"

        alpha_listener_id = await executor.register_listener(
            make_listener_registration(
                instance_name="alpha",
                app_key=app_key,
                name="sibling_listener",
            )
        )
        alpha_job_id = await executor.register_job(
            make_job_registration(
                instance_name="alpha",
                app_key=app_key,
                job_name="sibling_job",
            )
        )
        beta_listener_id = await executor.register_listener(
            make_listener_registration(
                instance_name="beta",
                app_key=app_key,
                name="reloaded_listener",
            )
        )
        beta_job_id = await executor.register_job(
            make_job_registration(
                instance_name="beta",
                app_key=app_key,
                job_name="reloaded_job",
            )
        )

        await lifecycle.reload_instance(app_key, "beta")

        alpha_listener_cursor = await db_service.db.execute(
            "SELECT id, retired_at FROM listeners WHERE id = ?", (alpha_listener_id,)
        )
        alpha_listener_row = await alpha_listener_cursor.fetchone()
        assert alpha_listener_row is not None, "sibling alpha's listener row must survive reload of beta"
        assert alpha_listener_row["retired_at"] is None, "sibling alpha's listener row must not be retired"

        alpha_job_cursor = await db_service.db.execute(
            "SELECT id, retired_at FROM scheduled_jobs WHERE id = ?", (alpha_job_id,)
        )
        alpha_job_row = await alpha_job_cursor.fetchone()
        assert alpha_job_row is not None, "sibling alpha's job row must survive reload of beta"
        assert alpha_job_row["retired_at"] is None, "sibling alpha's job row must not be retired"

        beta_listener_cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (beta_listener_id,))
        assert await beta_listener_cursor.fetchone() is None, (
            "beta's stale listener row should be cleaned up by its own reload"
        )

        beta_job_cursor = await db_service.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (beta_job_id,))
        assert await beta_job_cursor.fetchone() is None, "beta's stale job row should be cleaned up by its own reload"

    async def test_batch_reload_stops_every_instance_before_creating_any_replacement(
        self, real_db_lifecycle: tuple[AppLifecycleService, CommandExecutor, DatabaseService]
    ) -> None:
        """Regression test for PR #1687 review finding: a batch reload can make a *new* instance take an
        ``instance_name`` (and therefore ``App.unique_name``/owner_id) still held by a running instance —
        here ``beta`` keeps its name with a new config while ``alpha`` leaves and ``gamma`` arrives. Bus owner
        registries (``BusService.router``, ``BusService._removal_callbacks``) are keyed by that name string
        alone, so a create that ran before the old ``beta`` finished tearing down could register a listener
        that the old teardown's ``remove_listeners_by_owner("beta")`` then rips out too, since both are
        indistinguishable by owner_id alone.

        Proven deterministically by delaying ``beta``'s stop and observing that no create is ever attempted
        while that stop is still pending — the stop-all-then-create-all split makes this ordering structural,
        not timing-dependent. A reload that interleaved each instance's stop-then-create would start
        ``gamma``'s create immediately, well before ``beta``'s delayed stop completes.
        """
        lifecycle, _executor, _db_service = real_db_lifecycle
        app_key = self.MULTI_INSTANCE_APP_KEY
        original_manifest = self._make_manifest(
            [
                {"value": "a", "instance_name": "alpha"},
                {"value": "b", "instance_name": "beta"},
            ]
        )
        lifecycle.set_apps_configs({app_key: original_manifest})

        await lifecycle.start_app(app_key)
        beta_before = lifecycle.registry.get(app_key, "beta")
        assert beta_before is not None, "Precondition: beta should be running"
        assert beta_before.unique_name == "beta"

        original_config = deepcopy(lifecycle.registry.manifests)
        # One edit: alpha leaves the config, beta takes a new config, gamma arrives.
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "b2", "instance_name": "beta"},
            {"value": "c", "instance_name": "gamma"},
        ]

        call_order: list[str] = []
        beta_stop_entered = asyncio.Event()
        release_beta_stop = asyncio.Event()

        orig_stop = lifecycle._stop_instance_unlocked
        orig_create = lifecycle._create_instance_unlocked

        async def instrumented_stop(app_key: str, instance_name: str, *, outcomes: ActionOutcomes) -> None:
            if instance_name == "beta":
                beta_stop_entered.set()
                await release_beta_stop.wait()
            await orig_stop(app_key, instance_name, outcomes=outcomes)
            call_order.append(f"stop_{instance_name}_done")

        async def instrumented_create(
            app_key: str,
            instance_name: str,
            app_manifest: AppManifest,
            force_reload: bool = False,
            *,
            outcomes: ActionOutcomes,
        ) -> None:
            call_order.append(f"create_{instance_name}_start")
            await orig_create(app_key, instance_name, app_manifest, force_reload, outcomes=outcomes)

        lifecycle._stop_instance_unlocked = instrumented_stop
        lifecycle._create_instance_unlocked = instrumented_create

        changes = make_change_set(reload_apps={app_key})
        task = asyncio.create_task(lifecycle.apply_changes(changes, original_config, lifecycle.registry.manifests))

        await asyncio.wait_for(beta_stop_entered.wait(), timeout=1)
        # While beta's stop of the old, name-colliding instance is still pending, no create for any
        # instance may have started yet — the stop-all-then-create-all split forbids it structurally,
        # not just by timing luck.
        await asyncio.sleep(0)  # let any wrongly-scheduled create task get a chance to run
        assert not any(entry.startswith("create_") for entry in call_order), (
            f"a create started before beta's stop finished: {call_order}"
        )
        assert not task.done()

        release_beta_stop.set()
        await asyncio.wait_for(task, timeout=2)

        # Every stop finished strictly before every create started.
        stop_done_positions = [i for i, entry in enumerate(call_order) if entry.startswith("stop_")]
        create_start_positions = [i for i, entry in enumerate(call_order) if entry.startswith("create_")]
        assert stop_done_positions
        assert create_start_positions
        assert max(stop_done_positions) < min(create_start_positions), call_order

        # Sanity: the new "beta" came out of the reload fully usable — it can register a listener under
        # the now-uncontested "beta" owner_id. The ordering assertions above are what actually prove the
        # race is closed; this just confirms the flow doesn't leave the replacement in a broken state.
        beta_after = lifecycle.registry.get(app_key, "beta")
        assert beta_after is not None
        assert beta_after is not beta_before
        assert beta_after.unique_name == "beta"

        sub = await beta_after.bus.on(topic="test.race_topic", handler=noop, name="post_reload_listener")
        owner_listeners = lifecycle.hassette.bus_service.get_listeners_by_owner("beta")
        assert sub.listener.listener_id in {listener.listener_id for listener in owner_listeners}

"""Reload decisions under the app-key lock, the needs-restart replacement gate (#3110), and the per-instance
outcomes each lifecycle action returns (#3111).
"""

import asyncio
import typing
from collections.abc import Awaitable, Callable
from copy import deepcopy

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_lifecycle_common import NO_OUTCOME_REASON, ActionOutcomes
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry
from hassette.exceptions import AppBlockedError, AppRemovedError
from hassette.schemas.app_outcomes import InstanceOutcome, OutcomeResult
from hassette.testing import HassetteHarness, wait_for
from hassette.types.enums import BlockReason
from tests.support.factories import make_change_set, make_test_app_manifest

MULTI_INSTANCE_APP_KEY = "multi_instance"
STOP_TIMEOUT_REASON = "on_shutdown timed out"


def multi_instance_manifest(app_config: list[dict] | None = None) -> AppManifest:
    """The ``multi_instance`` test app's manifest; two instances, ``alpha`` and ``beta``, unless given a config."""
    if app_config is None:
        app_config = [{"value": "a", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}]
    return make_test_app_manifest(
        MULTI_INSTANCE_APP_KEY, "multi_instance_app.py", "MultiInstanceApp", app_config, display_name="Multi Instance"
    )


def flag(lifecycle: AppLifecycleService, name: str) -> None:
    """Flag instance ``name`` of the multi-instance app as needing a restart, as a teardown that left work running."""
    lifecycle.registry.flag_needs_restart(
        MULTI_INSTANCE_APP_KEY, name, class_name="MultiInstanceApp", reason="work still running"
    )


def summarize(outcomes: typing.Iterable[InstanceOutcome]) -> list[tuple[str, OutcomeResult, bool, str | None]]:
    """Each outcome as ``(name, result, needs_restart, reason)``, for comparing a whole action at once."""
    return [(o.instance_name, o.result, o.needs_restart, o.reason) for o in outcomes]


StopUnlocked = Callable[..., Awaitable[None]]


async def stopped_app_summary(lifecycle: AppLifecycleService) -> list[tuple[str, OutcomeResult, bool, str | None]]:
    """Stop the whole multi-instance app and ``summarize`` its outcomes."""
    return summarize(await lifecycle.stop_app(MULTI_INSTANCE_APP_KEY))


async def reloaded_instance_summary(
    lifecycle: AppLifecycleService,
) -> list[tuple[str, OutcomeResult, bool, str | None]]:
    """Reload instance ``alpha`` of the multi-instance app and ``summarize`` its outcome."""
    return summarize(await lifecycle.reload_instance(MULTI_INSTANCE_APP_KEY, "alpha"))


def fail_each_stop(lifecycle: AppLifecycleService, monkeypatch: pytest.MonkeyPatch, *, flags: bool) -> None:
    """Make each per-instance stop end failed with ``STOP_TIMEOUT_REASON`` (see ``stop_then_record``)."""
    monkeypatch.setattr(
        lifecycle, "_stop_instance_unlocked", stop_then_record(lifecycle, reason=STOP_TIMEOUT_REASON, flags=flags)
    )


def stop_then_record(lifecycle: AppLifecycleService, *, reason: str, flags: bool) -> StopUnlocked:
    """Wrap ``_stop_instance_unlocked`` so each stop ends failed with ``reason``, flagging the instance when ``flags``.

    Stands in for an ``on_shutdown`` that timed out: restart-safe when ``flags`` is false, leaving work running
    when it is true.
    """
    orig_stop = lifecycle._stop_instance_unlocked

    async def stop(app_key: str, name: str, *, outcomes: ActionOutcomes) -> None:
        await orig_stop(app_key, name, outcomes=outcomes)
        if flags:
            flag(lifecycle, name)
        outcomes.failed(name, reason, needs_restart=flags)

    return stop


async def record_nothing(*_args: object, **_kwargs: object) -> None:
    """A ``shutdown_instances`` stand-in that tears nothing down and records no outcome."""


async def blow_up(*_args: object, **_kwargs: object) -> None:
    """A ``shutdown_instances`` stand-in whose teardown raises."""
    raise RuntimeError("teardown blew up")


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
            await lifecycle._stop_app_unlocked(
                app_key, outcomes=lifecycle._outcomes_for(app_key, lifecycle._stop_targets(app_key))
            )
        await asyncio.wait_for(task, timeout=2)

        assert lifecycle.registry.get_running_apps(app_key) == {}

    async def test_batch_reload_does_not_create_over_an_instance_its_own_stop_flagged(
        self, lifecycle: AppLifecycleService
    ) -> None:
        """A stop earlier in the same batch that flags its instance blocks that instance's replacement (#1689 gap 2).

        The sibling's replacement is still created, and the flagged instance keeps reporting FAILED with its
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

        async def stop_that_leaves_work_running(app_key: str, instance_name: str, *, outcomes: ActionOutcomes) -> None:
            await orig_stop(app_key, instance_name, outcomes=outcomes)
            if instance_name == "beta":
                lifecycle.registry.flag_needs_restart(
                    app_key, "beta", class_name="MultiInstanceApp", reason="work still running"
                )

        lifecycle._stop_instance_unlocked = stop_that_leaves_work_running

        await lifecycle.apply_changes(
            make_change_set(reload_apps={app_key}), original_config, lifecycle.registry.manifests
        )

        alpha = lifecycle.registry.get(app_key, "alpha")
        assert alpha is not None
        assert alpha.app_config.model_dump()["value"] == "a2"
        assert lifecycle.registry.get(app_key, "beta") is None
        info = lifecycle.registry.resolve_instance_info(app_key, "beta")
        assert info is not None
        assert info.needs_restart is not None

    async def test_a_flag_follows_its_instance_across_a_reorder(self, lifecycle: AppLifecycleService) -> None:
        """After a reorder the flagged instance is still the one refused, and its outcome reports its new position."""
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)
        await lifecycle.stop_app(app_key)
        flag(lifecycle, "beta")

        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "b", "instance_name": "beta"},
            {"value": "a", "instance_name": "alpha"},
        ]
        outcomes = await lifecycle.start_app(app_key)

        assert [(o.instance_name, o.result) for o in outcomes] == [
            ("beta", OutcomeResult.REFUSED),
            ("alpha", OutcomeResult.SUCCEEDED),
        ]
        assert lifecycle.registry.get(app_key, "beta") is None
        assert lifecycle.registry.get(app_key, "alpha") is not None

    async def test_a_renamed_flagged_instance_starts_while_the_old_name_stays_failed(
        self, lifecycle: AppLifecycleService
    ) -> None:
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)
        await lifecycle.stop_instance(app_key, "beta")
        flag(lifecycle, "beta")

        original_config = deepcopy(lifecycle.registry.manifests)
        lifecycle.registry.manifests[app_key].app_config = [
            {"value": "a", "instance_name": "alpha"},
            {"value": "b", "instance_name": "beta_renamed"},
        ]
        await lifecycle.apply_changes(
            make_change_set(reload_apps={app_key}), original_config, lifecycle.registry.manifests
        )

        assert lifecycle.registry.get(app_key, "beta_renamed") is not None
        old = lifecycle.registry.resolve_instance_info(app_key, "beta")
        assert old is not None
        assert old.needs_restart is not None

    async def test_stop_reports_an_orphan_after_the_configured_instances(self, lifecycle: AppLifecycleService) -> None:
        """A running instance outside the config stays stoppable, under the name the instance list shows for it."""
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)
        lifecycle.registry.manifests[app_key].app_config = [{"value": "a", "instance_name": "alpha"}]

        outcomes = await lifecycle.stop_instance(app_key, "beta")

        assert [(o.instance_name, o.result) for o in outcomes] == [("beta", OutcomeResult.SUCCEEDED)]
        assert lifecycle.registry.get(app_key, "beta") is None

    async def test_reload_app_recreates_siblings_but_not_a_flagged_instance(
        self,
        lifecycle: AppLifecycleService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A whole-app reload refuses a flagged instance in its outcomes and recreates its siblings.

        The reload's create goes through ``AppFactory.create_instances``. The refusal reaches the caller
        through the outcome, so nothing logs it.
        """
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        await lifecycle.start_app(app_key)
        await lifecycle.stop_instance(app_key, "alpha")
        lifecycle.registry.flag_needs_restart(
            app_key, "alpha", class_name="MultiInstanceApp", reason="work still running"
        )
        beta_before = lifecycle.registry.get(app_key, "beta")

        outcomes = await lifecycle.reload_app(app_key)

        assert lifecycle.registry.get(app_key, "alpha") is None
        beta_after = lifecycle.registry.get(app_key, "beta")
        assert beta_after is not None
        assert beta_after is not beta_before
        assert [(o.instance_name, o.result, o.needs_restart) for o in outcomes] == [
            ("alpha", OutcomeResult.REFUSED, True),
            ("beta", OutcomeResult.SUCCEEDED, False),
        ]
        assert outcomes[0].reason == lifecycle.registry.refusal_reason(app_key, "alpha")
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    async def test_start_app_with_every_instance_flagged_starts_nothing_and_does_not_raise(
        self,
        lifecycle: AppLifecycleService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A start with nothing left to create refuses every instance, logs nothing, and leaves both flags."""
        app_key = MULTI_INSTANCE_APP_KEY
        lifecycle.set_apps_configs({app_key: multi_instance_manifest()})
        for name in ("alpha", "beta"):
            lifecycle.registry.flag_needs_restart(
                app_key, name, class_name="MultiInstanceApp", reason="work still running"
            )

        outcomes = await lifecycle.start_app(app_key)

        assert lifecycle.registry.get_running_apps(app_key) == {}
        infos = lifecycle.registry.resolve_instance_infos(app_key)
        assert sorted(infos) == ["alpha", "beta"]
        assert all(info.needs_restart is not None for info in infos.values())
        assert [(o.instance_name, o.result) for o in outcomes] == [
            ("alpha", OutcomeResult.REFUSED),
            ("beta", OutcomeResult.REFUSED),
        ]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]


class TestActionOutcomes:
    """Each start, stop and reload returns one outcome per targeted instance, decided under the app-key lock."""

    @pytest.fixture
    async def running(self, lifecycle: AppLifecycleService) -> AppLifecycleService:
        """The multi-instance app with both instances, ``alpha`` and ``beta``, running."""
        lifecycle.set_apps_configs({MULTI_INSTANCE_APP_KEY: multi_instance_manifest()})
        await lifecycle.start_app(MULTI_INSTANCE_APP_KEY)
        assert len(lifecycle.registry.get_running_apps(MULTI_INSTANCE_APP_KEY)) == 2, "Precondition: both running"
        return lifecycle

    async def test_start_reports_already_running_instances(self, running: AppLifecycleService) -> None:
        outcomes = await running.start_app(MULTI_INSTANCE_APP_KEY)

        assert summarize(outcomes) == [
            ("alpha", OutcomeResult.SUCCEEDED, False, "already running"),
            ("beta", OutcomeResult.SUCCEEDED, False, "already running"),
        ]

    async def test_stop_reports_every_configured_instance_including_one_already_stopped(
        self, running: AppLifecycleService
    ) -> None:
        await running.stop_instance(MULTI_INSTANCE_APP_KEY, "beta")

        assert await stopped_app_summary(running) == [
            ("alpha", OutcomeResult.SUCCEEDED, False, None),
            ("beta", OutcomeResult.SUCCEEDED, False, "already stopped"),
        ]

    async def test_stop_also_targets_a_tracked_instance_outside_the_config(self, running: AppLifecycleService) -> None:
        running.registry.manifests[MULTI_INSTANCE_APP_KEY].app_config = [{"value": "a", "instance_name": "alpha"}]

        outcomes = await running.stop_app(MULTI_INSTANCE_APP_KEY)

        assert [(o.instance_name, o.result) for o in outcomes] == [
            ("alpha", OutcomeResult.SUCCEEDED),
            ("beta", OutcomeResult.SUCCEEDED),
        ]
        assert running.registry.get_running_apps(MULTI_INSTANCE_APP_KEY) == {}

    @pytest.mark.parametrize("per_instance", [False, True], ids=["stop_app", "stop_instance"])
    async def test_stop_refuses_an_instance_already_flagged(
        self, running: AppLifecycleService, per_instance: bool
    ) -> None:
        """A flagged instance's work may still be running, so a stop never reports it stopped (spec 140 D3)."""
        await running.stop_instance(MULTI_INSTANCE_APP_KEY, "beta")
        flag(running, "beta")

        if per_instance:
            outcomes = await running.stop_instance(MULTI_INSTANCE_APP_KEY, "beta")
        else:
            outcomes = await running.stop_app(MULTI_INSTANCE_APP_KEY)

        refused = outcomes[-1]
        assert (refused.instance_name, refused.result, refused.needs_restart) == ("beta", OutcomeResult.REFUSED, True)
        assert refused.reason == running.registry.refusal_reason(MULTI_INSTANCE_APP_KEY, "beta")

    async def test_stop_whose_teardown_records_nothing_fails_closed(
        self, running: AppLifecycleService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a target untracked when the stop chose it is "already stopped"; a running one needs a record (D1)."""
        monkeypatch.setattr(running, "shutdown_instances", record_nothing)

        assert await stopped_app_summary(running) == [
            ("alpha", OutcomeResult.FAILED, False, NO_OUTCOME_REASON),
            ("beta", OutcomeResult.FAILED, False, NO_OUTCOME_REASON),
        ]

    async def test_per_instance_stop_over_a_shared_collector_decides_only_its_instance(
        self, running: AppLifecycleService
    ) -> None:
        """A config restart's per-instance stops share one collector; one never decides a sibling still stopping."""
        shared = running._outcomes_for(MULTI_INSTANCE_APP_KEY, ["alpha", "beta"])

        async with running._get_app_key_lock(MULTI_INSTANCE_APP_KEY):
            await running._stop_instance_unlocked(MULTI_INSTANCE_APP_KEY, "alpha", outcomes=shared)

        assert summarize(shared.snapshot()) == [("alpha", OutcomeResult.SUCCEEDED, False, None)]

    async def test_per_instance_stop_that_raises_fails_only_its_instance(
        self, running: AppLifecycleService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raising per-instance stop over a shared collector never fails a sibling still stopping."""
        shared = running._outcomes_for(MULTI_INSTANCE_APP_KEY, ["alpha", "beta"])

        monkeypatch.setattr(running, "shutdown_instances", blow_up)
        async with running._get_app_key_lock(MULTI_INSTANCE_APP_KEY):
            await running._stop_instance_unlocked(MULTI_INSTANCE_APP_KEY, "alpha", outcomes=shared)

        assert summarize(shared.snapshot()) == [("alpha", OutcomeResult.FAILED, False, "teardown blew up")]

    async def test_unexpected_raise_fails_every_target_with_its_message(
        self, running: AppLifecycleService, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception escaping the stop body still leaves one outcome per target (spec 140 D5)."""
        monkeypatch.setattr(running, "shutdown_instances", blow_up)

        assert await stopped_app_summary(running) == [
            ("alpha", OutcomeResult.FAILED, False, "teardown blew up"),
            ("beta", OutcomeResult.FAILED, False, "teardown blew up"),
        ]
        assert [r.getMessage().splitlines()[0] for r in caplog.records if r.levelname == "ERROR"] == [
            f"Failed to stop app {MULTI_INSTANCE_APP_KEY}:"
        ]

    async def test_reload_after_a_restart_safe_stop_failure_reports_success(
        self, running: AppLifecycleService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The create half decides a reload's outcome; the stop failure before it stays in ``reason`` (spec 140 D6)."""
        fail_each_stop(running, monkeypatch, flags=False)

        assert await reloaded_instance_summary(running) == [
            ("alpha", OutcomeResult.SUCCEEDED, False, "the stop before it failed: on_shutdown timed out"),
        ]
        assert running.registry.get(MULTI_INSTANCE_APP_KEY, "alpha") is not None

    async def test_reload_whose_create_fails_after_a_stop_failure_keeps_both_reasons(
        self, running: AppLifecycleService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing create half still reports the stop failure before it (spec 140 D6)."""
        fail_each_stop(running, monkeypatch, flags=False)

        async def create_fails(_app_key: str, name: str, *_args: object, outcomes: ActionOutcomes) -> None:
            outcomes.failed(name, "class failed to load")

        monkeypatch.setattr(running, "_create_instance_unlocked", create_fails)

        assert await reloaded_instance_summary(running) == [
            (
                "alpha",
                OutcomeResult.FAILED,
                False,
                "class failed to load; the stop before it failed: on_shutdown timed out",
            ),
        ]

    async def test_reload_whose_stop_flags_the_instance_reports_that_failure(
        self, running: AppLifecycleService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The create half's refusal doesn't relabel a zombie this reload created (spec 140 D6)."""
        fail_each_stop(running, monkeypatch, flags=True)

        assert await reloaded_instance_summary(running) == [
            ("alpha", OutcomeResult.FAILED, True, "on_shutdown timed out")
        ]
        assert running.registry.get(MULTI_INSTANCE_APP_KEY, "alpha") is None

    async def test_blocked_reload_carries_the_stop_outcomes(self, running: AppLifecycleService) -> None:
        running.registry.block_app(MULTI_INSTANCE_APP_KEY, BlockReason.ONLY_APP)

        with pytest.raises(AppBlockedError) as exc_info:
            await running.reload_app(MULTI_INSTANCE_APP_KEY)

        assert [(o.instance_name, o.result) for o in exc_info.value.outcomes] == [
            ("alpha", OutcomeResult.SUCCEEDED),
            ("beta", OutcomeResult.SUCCEEDED),
        ]
        assert running.registry.get_running_apps(MULTI_INSTANCE_APP_KEY) == {}

    async def test_start_of_an_app_with_no_manifest_raises_app_removed(self, lifecycle: AppLifecycleService) -> None:
        with pytest.raises(AppRemovedError):
            await lifecycle.start_app(MULTI_INSTANCE_APP_KEY)


class TestRefusalsWithNoResponseChannel:
    """A refused instance reached by a caller with no response is logged as exactly one ERROR."""

    @pytest.fixture
    async def flagged(self, lifecycle: AppLifecycleService) -> AppLifecycleService:
        """The multi-instance app running, except ``alpha``, which is stopped and flagged needs-restart."""
        lifecycle.set_apps_configs({MULTI_INSTANCE_APP_KEY: multi_instance_manifest()})
        await lifecycle.start_app(MULTI_INSTANCE_APP_KEY)
        await lifecycle.stop_instance(MULTI_INSTANCE_APP_KEY, "alpha")
        flag(lifecycle, "alpha")
        return lifecycle

    @staticmethod
    def refusal_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]

    @pytest.mark.parametrize(
        "new_config",
        [
            [{"value": "a2", "instance_name": "alpha"}, {"value": "b", "instance_name": "beta"}],
            [{"value": "a2", "instance_name": "alpha"}, {"value": "b2", "instance_name": "beta"}],
        ],
        ids=["changed-instance-restart", "whole-app-restart"],
    )
    async def test_config_change(
        self, flagged: AppLifecycleService, caplog: pytest.LogCaptureFixture, new_config: list[dict]
    ) -> None:
        original_config = deepcopy(flagged.registry.manifests)
        flagged.registry.manifests[MULTI_INSTANCE_APP_KEY].app_config = new_config

        await flagged.apply_changes(
            make_change_set(reload_apps={MULTI_INSTANCE_APP_KEY}), original_config, flagged.registry.manifests
        )

        reason = flagged.registry.refusal_reason(MULTI_INSTANCE_APP_KEY, "alpha")
        app = repr(MULTI_INSTANCE_APP_KEY)
        assert self.refusal_errors(caplog) == [
            f"Not starting alpha (app {app}): it {reason}. Restart hassette to run it again"
        ]

    async def test_bootstrap_start(self, flagged: AppLifecycleService, caplog: pytest.LogCaptureFixture) -> None:
        await flagged.stop_app(MULTI_INSTANCE_APP_KEY)
        caplog.clear()

        await flagged.start_apps({MULTI_INSTANCE_APP_KEY})

        assert len(self.refusal_errors(caplog)) == 1
        assert self.refusal_errors(caplog)[0].startswith("Not starting alpha")

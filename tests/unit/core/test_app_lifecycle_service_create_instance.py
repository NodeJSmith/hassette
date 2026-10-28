"""Unit tests for AppLifecycleService — the per-instance create path (``_create_instance_unlocked``).

Part of the AppLifecycleService unit-test family (``test_app_lifecycle_service*.py``);
shared fixtures live in ``_fixtures_app_lifecycle.py`` via ``conftest.py``.
"""

from unittest.mock import ANY, AsyncMock, MagicMock, Mock

import pytest
from hassette_wire import ResourceStatus

from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.exceptions import AppBlockedError
from hassette.schemas.app_outcomes import OutcomeResult
from hassette.testing import EventCapture
from hassette.types.enums import BlockReason
from tests.support.outcomes import AnyIndexOutcomes
from tests.support.web_manifest_helpers import make_app_instance_info

from .conftest import app_state_payloads, make_mock_app_instance


class TestCreateInstanceUnlockedSynchronousFailure:
    async def test_returns_early_without_initializing_when_create_single_instance_fails_synchronously(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
        event_capture: EventCapture,
    ) -> None:
        """create_single_instance() can register a failure synchronously (e.g. a config
        validation error at instance-creation time, not a class-load error) without raising.
        _create_instance_unlocked must notice that nothing was registered, emit the
        recorded failure, and return early rather than proceeding to initialize_instances().
        """
        event_capture.install(mock_hassette)
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        failure_info = make_app_instance_info(
            app_key="test_app",
            index=0,
            instance_name="test_app.0",
            class_name="TestApp",
            status=ResourceStatus.FAILED,
            error=ValueError("bad config"),
            error_message="bad config",
            error_traceback="Traceback...",
        )
        mock_registry.get_failed_instance_infos = Mock(return_value={0: failure_info})

        lifecycle_service.initialize_instances = AsyncMock()

        await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest, outcomes=AnyIndexOutcomes())

        mock_factory.create_single_instance.assert_called_once()
        lifecycle_service.initialize_instances.assert_not_called()

        failed_payloads = app_state_payloads(event_capture, ResourceStatus.FAILED)
        assert len(failed_payloads) == 1


class TestCreateInstanceUnlockedPostRegistrationFailure:
    async def test_never_started_phantom_is_shut_down_with_its_own_hooks_skipped(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        mock_hassette: MagicMock,
    ) -> None:
        """If send_event raises after create_single_instance registered the app but before its
        initialization started, the phantom is shut down with the exception as its cause and its
        own shutdown hooks skipped — an app that never initialized must not run ``on_shutdown``.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        mock_registry.get = Mock(return_value=mock_inst)

        failure = RuntimeError("event bus failure")
        mock_hassette.send_event = AsyncMock(side_effect=failure)
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="event bus failure"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest, outcomes=AnyIndexOutcomes())

        lifecycle_service.shutdown_instance.assert_awaited_once_with(mock_inst, 0, cause=failure, outcomes=ANY)
        assert mock_inst._skip_own_shutdown_hooks is True

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_initialized_phantom_is_shut_down_with_its_own_hooks(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """An app that initialized before something after it raised (reconciliation) gets its
        ``on_shutdown``: the phantom is shut down with the cause, without the hook skip.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        mock_registry.get = Mock(return_value=mock_inst)

        failure = RuntimeError("reconcile failed")
        lifecycle_service.initialize_instances = AsyncMock(side_effect=failure)
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="reconcile failed"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest, outcomes=AnyIndexOutcomes())

        lifecycle_service.shutdown_instance.assert_awaited_once_with(mock_inst, 0, cause=failure, outcomes=ANY)
        assert mock_inst._skip_own_shutdown_hooks is False

    # dup-ignore-start: pytest test function signature (see .claude/rules/tests-unit-core.md)
    async def test_phantom_already_gone_records_a_post_registration_failure(
        self,
        lifecycle_service: AppLifecycleService,
        mock_registry: MagicMock,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
    ) -> None:
        # dup-ignore-end
        """When nothing is registered at the index any more, there is nothing to shut down; the
        failure is recorded so the index doesn't silently look stopped.
        """
        mock_manifest.app_config = [{"instance_name": "a"}]
        mock_factory.normalize_configs = Mock(side_effect=lambda cfg: cfg)
        mock_factory.load_class = Mock(return_value=MagicMock())

        mock_inst = make_mock_app_instance()
        lookups = iter([mock_inst])
        mock_registry.get = Mock(side_effect=lambda _key, _index=0: next(lookups, None))
        lifecycle_service.initialize_instances = AsyncMock(side_effect=RuntimeError("reconcile failed"))
        lifecycle_service.shutdown_instance = AsyncMock()

        with pytest.raises(RuntimeError, match="reconcile failed"):
            await lifecycle_service._create_instance_unlocked("test_app", 0, mock_manifest, outcomes=AnyIndexOutcomes())

        lifecycle_service.shutdown_instance.assert_not_called()
        mock_registry.record_failure.assert_called_once()
        assert mock_registry.record_failure.call_args.args[:2] == ("test_app", 0)


class TestCreateInstanceUnlockedNeedsRestartGate:
    async def test_flagged_index_is_refused_before_the_class_is_loaded(
        self,
        real_registry_service: AppLifecycleService,
        mock_factory: MagicMock,
        mock_manifest: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A start or reload over a flagged index records a refusal and returns without raising or logging. The
        module isn't re-imported, and no class-load failure is recorded over the flag.
        """
        registry = real_registry_service.registry
        registry.flag_needs_restart(
            "test_app", 0, instance_name="zombie", class_name="TestApp", reason="work still running"
        )
        outcomes = AnyIndexOutcomes()

        await real_registry_service._create_instance_unlocked(
            "test_app", 0, mock_manifest, force_reload=True, outcomes=outcomes
        )

        mock_factory.load_class.assert_not_called()
        mock_factory.create_single_instance.assert_not_called()
        assert registry.get_instances("test_app") == {}
        assert [(o.result, o.reason) for o in outcomes.snapshot()] == [
            (OutcomeResult.REFUSED, registry.refusal_reason("test_app", 0))
        ]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    async def test_blocked_check_still_runs_before_the_flag_check(
        self,
        real_registry_service: AppLifecycleService,
        mock_manifest: MagicMock,
    ) -> None:
        """A blocked app still raises AppBlockedError even when the index is also flagged."""
        registry = real_registry_service.registry
        registry.flag_needs_restart(
            "test_app", 0, instance_name="zombie", class_name="TestApp", reason="work still running"
        )
        registry.block_app("test_app", BlockReason.ONLY_APP)

        with pytest.raises(AppBlockedError):
            await real_registry_service._create_instance_unlocked(
                "test_app", 0, mock_manifest, outcomes=AnyIndexOutcomes()
            )

    async def test_start_instance_over_a_flagged_index_does_not_raise_or_log_twice(
        self,
        real_registry_service: AppLifecycleService,
        mock_manifest: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The public path returns the refusal without raising or logging: the HTTP response carries it."""
        registry = real_registry_service.registry
        registry.set_manifests({"test_app": mock_manifest})
        real_registry_service._instance_index_in_range = Mock(return_value=True)  # pyright: ignore[reportAttributeAccessIssue]
        registry.flag_needs_restart(
            "test_app", 0, instance_name="zombie", class_name="TestApp", reason="work still running"
        )

        outcomes = await real_registry_service.start_instance("test_app", 0)

        assert [(o.result, o.needs_restart, o.reason) for o in outcomes] == [
            (OutcomeResult.REFUSED, True, registry.refusal_reason("test_app", 0))
        ]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

"""The running-time commit of an instance's declared entities in ``initialize_instance`` (spec 157 D10)."""

import typing
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hassette_wire import ResourceStatus

from hassette.core import app_lifecycle_instances
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.schemas.app_outcomes import OutcomeResult
from tests.support.app_registry_helpers import seed_failed, seed_running
from tests.support.outcomes import AnyNameOutcomes

from .conftest import failure_writes


async def test_commit_runs_after_initialize_and_before_running(
    real_registry_service: AppLifecycleService, mock_app_instance: AsyncMock
) -> None:
    registry = real_registry_service.registry
    seed_running(registry, "test_app", mock_app_instance, status=ResourceStatus.NOT_STARTED)
    seen: list[object] = []
    mock_app_instance.initialize.side_effect = lambda: seen.append("initialize")

    async def commit() -> None:
        seen.append(("commit", registry.get_status("test_app", "test_instance")))

    mock_app_instance.integration.commit_declarations = AsyncMock(side_effect=commit)
    outcomes = AnyNameOutcomes()

    with patch.object(app_lifecycle_instances, "mark_ready"):
        await real_registry_service.initialize_instance(mock_app_instance, "TestApp", outcomes=outcomes)

    assert seen == ["initialize", ("commit", ResourceStatus.STARTING)]
    assert registry.get_status("test_app", "test_instance") is ResourceStatus.RUNNING
    [outcome] = outcomes.snapshot()
    assert outcome.result is OutcomeResult.SUCCEEDED


async def test_failed_commit_fails_the_instance_and_runs_its_shutdown_hooks(
    lifecycle_service: AppLifecycleService,
    mock_app_instance: AsyncMock,
    mock_registry: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = OSError("disk full")
    mock_app_instance.integration.commit_declarations = AsyncMock(side_effect=error)

    with patch.object(app_lifecycle_instances, "mark_ready"):
        await lifecycle_service.initialize_instance(mock_app_instance, "TestApp", outcomes=AnyNameOutcomes())

    mock_app_instance.shutdown.assert_awaited_once()
    assert getattr(mock_app_instance, "_skip_own_shutdown_hooks", False) is not True
    [write] = failure_writes(mock_registry)
    assert write.kwargs["error"] is error
    assert "Failed to commit the declared entities" in caplog.text


@pytest.mark.parametrize(
    "stop",
    [
        pytest.param(
            lambda registry: registry.set_status("test_app", "test_instance", ResourceStatus.STOPPING), id="stopping"
        ),
        pytest.param(
            lambda registry: seed_failed(registry, "test_app", "test_instance", needs_restart="work still running"),
            id="flagged",
        ),
    ],
)
async def test_an_instance_stopped_during_init_gets_no_commit(
    real_registry_service: AppLifecycleService,
    mock_app_instance: AsyncMock,
    stop: typing.Callable[[typing.Any], object],
) -> None:
    registry = real_registry_service.registry
    seed_running(registry, "test_app", mock_app_instance, status=ResourceStatus.NOT_STARTED)
    mock_app_instance.initialize.side_effect = lambda: stop(registry)
    mock_app_instance.integration.commit_declarations = AsyncMock()

    with patch.object(app_lifecycle_instances, "mark_ready"):
        await real_registry_service.initialize_instance(mock_app_instance, "TestApp", outcomes=AnyNameOutcomes())

    mock_app_instance.integration.commit_declarations.assert_not_awaited()

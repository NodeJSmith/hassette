"""App start and stop outcomes log at INFO, so they are visible at the default log level.

The log records are the contract here, so these tests read them with ``caplog`` and match on the
exact message template.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_lifecycle_common import AppAdmissionMode
from hassette.core.app_lifecycle_service import AppLifecycleService
from tests.support.outcomes import AnyNameOutcomes


def levels_logged(caplog: pytest.LogCaptureFixture, template: str) -> list[int]:
    """Return the level of each captured record whose unformatted message is ``template``."""
    return [record.levelno for record in caplog.records if record.msg == template]


async def initialize_instance(service: AppLifecycleService, inst: AsyncMock, manifest: MagicMock) -> None:
    await service.initialize_instances("test_app", {"test_instance": inst}, manifest, outcomes=AnyNameOutcomes())


async def test_app_start_logs_at_info(
    lifecycle_service: AppLifecycleService,
    mock_app_instance: AsyncMock,
    mock_manifest: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        await initialize_instance(lifecycle_service, mock_app_instance, mock_manifest)

    assert levels_logged(caplog, "App '%s' (%s) initialized successfully") == [logging.INFO]


async def test_bootstrap_summary_logs_at_info(
    lifecycle_service: AppLifecycleService, mock_registry: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_registry.manifests = {"app_a": MagicMock()}
    mock_registry.get_snapshot = Mock(return_value=MagicMock(running_count=1, failed_count=0))

    with caplog.at_level(logging.DEBUG):
        await lifecycle_service.bootstrap_apps(admission_mode=AppAdmissionMode.WAIT_FOR_RELEASE)

    assert levels_logged(caplog, "Initialized %d apps successfully, %d failed to start") == [logging.INFO]


async def test_app_stop_logs_at_info(
    lifecycle_service: AppLifecycleService, mock_app_instance: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await lifecycle_service.shutdown_instance(mock_app_instance, outcomes=AnyNameOutcomes())

    assert levels_logged(caplog, "Stopped app '%s' '%s' in %s") == [logging.INFO]


async def test_shutdown_after_failed_start_logs_at_info(
    lifecycle_service: AppLifecycleService,
    mock_app_instance: AsyncMock,
    mock_manifest: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_app_instance.initialize.side_effect = ValueError("boom")

    with caplog.at_level(logging.DEBUG):
        await initialize_instance(lifecycle_service, mock_app_instance, mock_manifest)

    assert levels_logged(caplog, "Shut down app '%s' (%s) after its failed start in %s") == [logging.INFO]

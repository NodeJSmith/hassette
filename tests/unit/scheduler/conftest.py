"""Shared fixtures for unit/scheduler tests."""

from unittest.mock import MagicMock

from hassette.scheduler import Scheduler


async def noop() -> None:
    pass


def make_scheduler() -> Scheduler:
    """Create a Scheduler with a stubbed hassette and scheduler_service."""
    hassette = MagicMock()
    hassette.config.logging.scheduler_service = "INFO"
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.hassette = hassette
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    scheduler.scheduler_service = MagicMock()
    scheduler._unique_name = "test_scheduler"
    scheduler._error_handler = None
    mock_parent = MagicMock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestParent"
    scheduler.parent = mock_parent
    return scheduler

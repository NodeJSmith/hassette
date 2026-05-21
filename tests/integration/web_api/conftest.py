"""Shared fixtures and helpers for web API integration tests."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from hassette.core.app_registry import AppInstanceInfo, AppStatusSnapshot
from hassette.test_utils.web_mocks import create_hassette_stub
from hassette.types.enums import ResourceStatus

LOGS_REPO = "hassette.web.routes.logs._repo"


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    _instance = AppInstanceInfo(
        app_key="my_app",
        index=0,
        instance_name="MyApp[0]",
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )
    return create_hassette_stub(
        run_web_ui=False,
        states={
            "light.kitchen": {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 255},
                "last_changed": "2024-01-01T00:00:00",
                "last_updated": "2024-01-01T00:00:00",
            },
            "sensor.temp": {
                "entity_id": "sensor.temp",
                "state": "21.5",
                "attributes": {"unit_of_measurement": "°C"},
                "last_changed": "2024-01-01T00:00:00",
                "last_updated": "2024-01-01T00:00:00",
            },
        },
        old_snapshot=AppStatusSnapshot(running=[_instance], failed=[]),
        app_action_mocks=True,
    )


def make_log_record(
    seq: int,
    level: str = "INFO",
    message: str = "test",
    app_key: str | None = None,
    execution_id: str | None = None,
    source_tier: str | None = "framework",
) -> dict:
    return {
        "seq": seq,
        "timestamp": float(seq),
        "level": level,
        "logger_name": "hassette.test",
        "func_name": "test_func",
        "lineno": 1,
        "message": message,
        "exc_info": None,
        "app_key": app_key,
        "execution_id": execution_id,
        "instance_name": None,
        "instance_index": None,
        "source_tier": source_tier,
    }


def mock_submit(return_value: object = None, side_effect: object = None) -> AsyncMock:
    """Create an AsyncMock for database_service.submit that closes the passed coroutine."""
    values = list(side_effect) if side_effect is not None else None
    call_count = [0]

    async def _impl(coro: object) -> object:
        if asyncio.iscoroutine(coro):
            coro.close()
        if values is not None:
            idx = min(call_count[0], len(values) - 1)
            call_count[0] += 1
            result = values[idx]
            if isinstance(result, BaseException):
                raise result
            return result
        return return_value

    mock = AsyncMock(side_effect=_impl)
    return mock

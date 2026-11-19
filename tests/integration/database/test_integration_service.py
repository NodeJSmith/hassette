"""IntegrationService against a real SQLite database (spec 157 D4, D10, D12, D13, parent D13)."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
from hassette_wire import ResourceStatus

from hassette.core.database_service import DatabaseService
from hassette.core.integration_service import CommandDispatchResult, IntegrationService
from hassette.integration.declarations import Declaration, EntityState, IntegrationPlatform
from hassette.integration.errors import IntegrationHandleClosedError

FEED = Declaration(key="feed", platform=IntegrationPlatform.BUTTON, name="Feed")
SHOW = Declaration(key="show", platform=IntegrationPlatform.SWITCH, name="Show", initial=True)
TEMP = Declaration(key="temp", platform=IntegrationPlatform.SENSOR, name="Temp", device_class="temperature", unit="°C")
TEMP_AS_ENUM = Declaration(
    key="temp", platform=IntegrationPlatform.SENSOR, name="Temp", device_class="enum", options=("hot", "cold")
)


def owner(instance_name: str = "kitchen") -> Any:
    """A stand-in for an instance's ``Integration``: the service reads only its identity."""
    return SimpleNamespace(app_key="my_app", instance_name=instance_name)


@pytest.fixture
async def db(initialized_service: DatabaseService) -> DatabaseService:
    hassette = cast("MagicMock", initialized_service.hassette)
    hassette.database_service = initialized_service
    return initialized_service


async def start_service(db: DatabaseService, configured: set[tuple[str, str]] | None = None) -> IntegrationService:
    """Build and initialize a service, as one hassette boot does."""
    service = IntegrationService(db.hassette, parent=None)
    configured = {("my_app", "kitchen")} if configured is None else configured
    service.configured_instances = lambda: configured  # pyright: ignore[reportAttributeAccessIssue]
    await service.on_initialize()
    return service


async def stored_rows(db: DatabaseService) -> list[tuple[Any, ...]]:
    cursor = await db.db.execute(
        "SELECT instance_name, key, platform, value, attributes FROM integration_entities ORDER BY instance_name, key"
    )
    return [tuple(row) for row in await cursor.fetchall()]


async def test_commit_persists_and_a_new_boot_restores_it(db: DatabaseService) -> None:
    service = await start_service(db)
    kitchen = owner()
    counts = await service.commit_instance(kitchen, [FEED, SHOW, TEMP], {"temp": EntityState(21.5, {"a": 1})})
    assert (counts.added, counts.kept, counts.removed) == (3, 0, 0)
    assert await stored_rows(db) == [
        ("kitchen", "feed", "button", None, None),
        ("kitchen", "show", "switch", "true", "{}"),
        ("kitchen", "temp", "sensor", "21.5", '{"a": 1}'),
    ]

    rebooted = await start_service(db)
    assert rebooted.boot_id != service.boot_id
    assert rebooted.revision == 0
    restored = {entity.declaration.key: entity.state for entity in rebooted.entities("my_app", "kitchen")}
    assert restored == {"feed": EntityState(), "show": EntityState(True, {}), "temp": EntityState(21.5, {"a": 1})}


async def test_recommit_keeps_state_ignores_new_initial_and_removes_dropped(db: DatabaseService) -> None:
    service = await start_service(db)
    await service.commit_instance(owner(), [FEED, SHOW, TEMP], {"temp": EntityState(21.5, {})})
    await service.set_job(service._owners[("my_app", "kitchen")], SHOW, EntityState(False, {}))

    rebooted = await start_service(db)
    off_by_default = Declaration(key="show", platform=IntegrationPlatform.SWITCH, name="Show", initial=False)
    counts = await rebooted.commit_instance(owner(), [off_by_default, TEMP], {})
    assert (counts.added, counts.kept, counts.removed) == (0, 2, 1)
    assert await stored_rows(db) == [
        ("kitchen", "show", "switch", "false", "{}"),
        ("kitchen", "temp", "sensor", "21.5", "{}"),
    ]


async def test_restored_value_that_no_longer_fits_is_reset(
    db: DatabaseService, caplog: pytest.LogCaptureFixture
) -> None:
    service = await start_service(db)
    await service.commit_instance(owner(), [TEMP], {"temp": EntityState(21.5, {"a": 1})})

    rebooted = await start_service(db)
    with caplog.at_level(logging.WARNING):
        await rebooted.commit_instance(owner(), [TEMP_AS_ENUM], {})
    assert rebooted.entities("my_app", "kitchen")[0].state == EntityState()
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", None, "{}")]
    assert "doesn't fit its changed declaration" in caplog.text


async def test_startup_prunes_unconfigured_instances(db: DatabaseService, caplog: pytest.LogCaptureFixture) -> None:
    service = await start_service(db, {("my_app", "kitchen"), ("my_app", "garage")})
    await service.commit_instance(owner("kitchen"), [TEMP], {})
    await service.commit_instance(owner("garage"), [TEMP, FEED], {})

    with caplog.at_level(logging.WARNING):
        rebooted = await start_service(db, {("my_app", "kitchen")})
    assert [row[0] for row in await stored_rows(db)] == ["kitchen"]
    assert rebooted.entities("my_app", "garage") == []
    assert "my_app/garage" in caplog.text


async def test_failed_commit_leaves_the_previous_set(db: DatabaseService, monkeypatch: pytest.MonkeyPatch) -> None:
    service = await start_service(db)
    first = owner()
    await service.commit_instance(first, [FEED, TEMP], {"temp": EntityState(1, {})})
    revision = service.revision

    real_executemany = db.db.executemany
    calls = 0

    async def fail_on_delete(sql: str, params: Any) -> aiosqlite.Cursor:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise aiosqlite.OperationalError("disk I/O error")
        return await real_executemany(sql, params)

    monkeypatch.setattr(db.db, "executemany", fail_on_delete)
    second = owner()
    with pytest.raises(aiosqlite.OperationalError):
        await service.commit_instance(second, [SHOW], {"show": EntityState(False, {})})
    monkeypatch.undo()

    assert await stored_rows(db) == [
        ("kitchen", "feed", "button", None, None),
        ("kitchen", "temp", "sensor", "1", "{}"),
    ]
    assert [entity.declaration.key for entity in service.entities("my_app", "kitchen")] == ["feed", "temp"]
    assert service.revision == revision
    with pytest.raises(IntegrationHandleClosedError):
        await service.set_state(second, TEMP, EntityState(2, {}))


async def test_set_writes_once_and_rejects_a_replaced_owner(db: DatabaseService) -> None:
    service = await start_service(db)
    old, new = owner(), owner()
    await service.commit_instance(old, [TEMP], {})
    await service.commit_instance(new, [TEMP], {})
    with pytest.raises(IntegrationHandleClosedError):
        await service.set_state(old, TEMP, EntityState(5, {}))

    revision = service.revision
    await service.set_state(new, TEMP, EntityState(5, {}))
    await service.set_state(new, TEMP, EntityState(5, {}))
    assert service.revision == revision + 1
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "5", "{}")]


async def test_dispatch_checks_running_and_declared(db: DatabaseService) -> None:
    service = await start_service(db)
    await service.commit_instance(owner(), [FEED, SHOW], {})
    hassette = cast("MagicMock", db.hassette)
    hassette.send_event = AsyncMock()
    hassette.app_handler = MagicMock()
    registry = hassette.app_handler.registry

    registry.get_status.return_value = ResourceStatus.FAILED
    assert await service.dispatch_command("my_app", "kitchen", "feed", "button") is CommandDispatchResult.NOT_RUNNING

    registry.get_status.return_value = ResourceStatus.RUNNING
    assert await service.dispatch_command("my_app", "kitchen", "nope", "button") is CommandDispatchResult.NOT_DECLARED
    assert await service.dispatch_command("my_app", "kitchen", "show", "button") is CommandDispatchResult.NOT_DECLARED
    hassette.send_event.assert_not_awaited()

    result = await service.dispatch_command("my_app", "kitchen", "show", "switch", True)
    assert result is CommandDispatchResult.DISPATCHED
    payload = hassette.send_event.await_args.args[0].payload.data
    assert (payload.key, payload.platform, payload.value) == ("show", "switch", True)

    with pytest.raises(ValueError, match="bool"):
        await service.dispatch_command("my_app", "kitchen", "show", "switch")
    with pytest.raises(ValueError, match="no commands"):
        await service.dispatch_command("my_app", "kitchen", "temp", "sensor")

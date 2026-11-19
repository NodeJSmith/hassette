"""IntegrationService against a real SQLite database (spec 157 D4, D10, D12, D13, parent D13)."""

import asyncio
import logging
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from hassette.core import integration_store
from hassette.core.database_service import DatabaseService
from hassette.core.integration_service import CommandDispatchResult, IntegrationService
from hassette.integration import Integration, IntegrationSensor
from hassette.integration.declarations import Declaration, EntityState, IntegrationPlatform
from hassette.integration.errors import IntegrationDeclarationClosedError, IntegrationHandleClosedError
from hassette.testing import wait_for
from tests.support.factories import make_app
from tests.support.helpers import async_noop

FEED = Declaration(key="feed", platform=IntegrationPlatform.BUTTON, name="Feed")
SHOW = Declaration(key="show", platform=IntegrationPlatform.SWITCH, name="Show", initial=True)
TEMP = Declaration(key="temp", platform=IntegrationPlatform.SENSOR, name="Temp", device_class="temperature", unit="°C")
TEMP_AS_ENUM = Declaration(
    key="temp", platform=IntegrationPlatform.SENSOR, name="Temp", device_class="enum", options=("hot", "cold")
)


def owner(instance_name: str = "kitchen") -> Any:
    """A stand-in for an instance's ``Integration``: the service reads only its identity."""
    return SimpleNamespace(
        app_key="my_app", instance_name=instance_name, instance_key=("my_app", instance_name), closed=False
    )


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


@pytest.mark.parametrize(
    ("bad_attributes", "bad_value", "bad_options"),
    [("not json", "not json", "not json"), ("[1]", "{}", "5"), ("null", "[]", "[1, 2]")],
    ids=["syntax", "wrong-shape", "wrong-element-type"],
)
async def test_corrupt_stored_rows_load_as_defaults_or_are_skipped(
    db: DatabaseService, caplog: pytest.LogCaptureFixture, bad_attributes: str, bad_value: str, bad_options: str
) -> None:
    service = await start_service(db)
    second = Declaration(
        key="humid", platform=IntegrationPlatform.SENSOR, name="Humid", device_class="enum", options=("a",)
    )
    await service.commit_instance(owner(), [SHOW, TEMP, second], {"temp": EntityState(21.5, {})})
    await db.db.execute("UPDATE integration_entities SET attributes = ? WHERE key = 'show'", (bad_attributes,))
    await db.db.execute("UPDATE integration_entities SET value = ? WHERE key = 'temp'", (bad_value,))
    await db.db.execute("UPDATE integration_entities SET options = ? WHERE key = 'humid'", (bad_options,))
    await db.db.commit()

    with caplog.at_level(logging.WARNING):
        rebooted = await start_service(db)
    restored = {entity.declaration.key: entity.state for entity in rebooted.entities("my_app", "kitchen")}
    assert restored == {"show": EntityState(True, {}), "temp": EntityState()}
    assert "doesn't parse" in caplog.text


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


async def test_dispatch_admits_only_a_live_owner_and_a_committed_key(db: DatabaseService) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    integration.register_listener = AsyncMock(return_value=MagicMock())  # pyright: ignore[reportAttributeAccessIssue]
    await integration.add_button("feed", name="Feed", on_press=async_noop)
    await integration.add_switch("show", name="Show", on_toggle=async_noop)
    await integration.add_sensor("temp", name="Temp")
    hassette = cast("MagicMock", db.hassette)
    hassette.send_event = AsyncMock()

    assert await service.dispatch_command("my_app", "kitchen", "feed", "button") is CommandDispatchResult.NOT_RUNNING
    await integration.commit_declarations()

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

    await integration.on_shutdown()
    hassette.send_event.reset_mock()
    assert await service.dispatch_command("my_app", "kitchen", "feed", "button") is CommandDispatchResult.NOT_RUNNING
    hassette.send_event.assert_not_awaited()


async def test_command_after_a_commit_that_lands_after_shutdown_is_not_running(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process exit landing while the commit is in flight: the commit lands, but nothing owns it."""
    service = await start_service(db)
    integration = make_integration(service)
    integration.register_listener = AsyncMock(return_value=MagicMock())  # pyright: ignore[reportAttributeAccessIssue]
    await integration.add_button("feed", name="Feed", on_press=async_noop)
    hassette = cast("MagicMock", db.hassette)
    hassette.send_event = AsyncMock()
    entered, release = gate(service, "persist_instance_set", monkeypatch)

    commit = asyncio.create_task(integration.commit_declarations())
    await asyncio.wait_for(entered.wait(), timeout=1)
    await integration.on_shutdown()
    release.set()
    await commit

    assert [entity.declaration.key for entity in service.entities("my_app", "kitchen")] == ["feed"]
    assert await service.dispatch_command("my_app", "kitchen", "feed", "button") is CommandDispatchResult.NOT_RUNNING
    hassette.send_event.assert_not_awaited()


async def test_instance_that_declared_nothing_is_running_but_has_no_such_key(db: DatabaseService) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    await integration.commit_declarations()
    assert service.admit_command("my_app", "kitchen", "feed", IntegrationPlatform.BUTTON, None) is (
        CommandDispatchResult.NOT_DECLARED
    )
    await integration.on_shutdown()
    assert service.admit_command("my_app", "kitchen", "feed", IntegrationPlatform.BUTTON, None) is (
        CommandDispatchResult.NOT_RUNNING
    )


def make_integration(service: IntegrationService) -> Integration:
    """A real ``Integration`` for instance ``my_app/kitchen``, on a bare app whose hassette points at ``service``."""
    app = make_app(app_key="my_app", instance_name="kitchen")
    cast("Any", app.hassette).integration_service = service
    return app.integration


async def declare_temp(integration: Integration, value: float | None = None) -> IntegrationSensor:
    sensor = await integration.add_sensor("temp", name="Temp", unit="°C", device_class="temperature")
    if value is not None:
        await sensor.set(value)
    return sensor


async def committed_temp(service: IntegrationService, value: float | None = None) -> IntegrationSensor:
    """Declare ``temp`` (optionally setting it during init) on a new ``Integration`` and commit it."""
    integration = make_integration(service)
    temp = await declare_temp(integration, value)
    await integration.commit_declarations()
    return temp


async def fail_with_disk_error(*_: Any) -> Any:
    raise aiosqlite.OperationalError("disk I/O error")


def gate(target: Any, name: str, monkeypatch: pytest.MonkeyPatch) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold ``target.name`` (an async method) at its start; returns ``(entered, release)``."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = getattr(target, name)

    async def held(*args: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(target, name, held)
    return entered, release


async def flush_writer(db: DatabaseService) -> None:
    """Wait until every write queued before this call has run."""
    await db.submit(async_noop())


async def test_commit_lands_when_its_caller_is_cancelled(db: DatabaseService, monkeypatch: pytest.MonkeyPatch) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 21.5)
    entered, release = gate(service, "persist_instance_set", monkeypatch)

    task = asyncio.create_task(integration.commit_declarations())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    await wait_for(lambda: service.is_owner(integration), desc="commit landed")
    assert temp.value == 21.5
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "21.5", "{}")]


async def test_started_set_takes_effect_when_its_caller_is_cancelled(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    temp = await committed_temp(service)
    entered, release = gate(service, "persist_state", monkeypatch)

    task = asyncio.create_task(temp.set(30))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await flush_writer(db)

    assert temp.value == 30
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "30", "{}")]


async def test_queued_set_is_withdrawn_when_its_caller_is_cancelled(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    temp = await committed_temp(service, 1)

    busy, free = asyncio.Event(), asyncio.Event()

    async def occupy_writer() -> None:
        busy.set()
        await free.wait()

    blocker = asyncio.create_task(db.submit(occupy_writer()))
    await asyncio.wait_for(busy.wait(), timeout=1)
    submitted = asyncio.Event()
    run_write = service.run_write

    async def signalled_run_write(coro: Coroutine[Any, Any, Any]) -> Any:
        submitted.set()
        return await run_write(coro)

    monkeypatch.setattr(service, "run_write", signalled_run_write)
    task = asyncio.create_task(temp.set(99))
    await asyncio.wait_for(submitted.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    free.set()
    await blocker
    await flush_writer(db)

    assert temp.value == 1
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "1", "{}")]


async def test_concurrent_sets_leave_memory_equal_to_the_stored_row(db: DatabaseService) -> None:
    service = await start_service(db)
    temp = await committed_temp(service)

    await asyncio.gather(*(temp.set(value) for value in range(10)))

    [row] = await stored_rows(db)
    assert row[3] == str(temp.value)


async def test_stop_during_the_commit_keeps_the_set_and_closes_the_handles(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 5)
    entered, release = gate(service, "persist_instance_set", monkeypatch)

    task = asyncio.create_task(integration.commit_declarations())
    await asyncio.wait_for(entered.wait(), timeout=1)
    await integration.on_shutdown()
    with pytest.raises(IntegrationHandleClosedError):
        await temp.set(7)
    release.set()
    await task

    assert [entity.state.value for entity in service.entities("my_app", "kitchen")] == [5]
    assert not service.is_owner(integration)
    with pytest.raises(IntegrationHandleClosedError):
        _ = temp.value
    with pytest.raises(IntegrationHandleClosedError):
        await temp.set(6)


async def test_failed_commit_closes_the_handles_and_discards_pending_values(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 5)

    monkeypatch.setattr(service, "persist_instance_set", fail_with_disk_error)
    with pytest.raises(aiosqlite.OperationalError):
        await integration.commit_declarations()
    monkeypatch.undo()

    with pytest.raises(IntegrationHandleClosedError):
        _ = temp.value
    with pytest.raises(IntegrationHandleClosedError):
        await temp.set(6)

    retried = make_integration(service)
    retried_temp = await declare_temp(retried)
    await retried.commit_declarations()
    assert retried_temp.value is None


async def test_instance_that_declares_nothing_writes_nothing(db: DatabaseService) -> None:
    service = await start_service(db)
    assert await make_integration(service).commit_declarations() is None
    assert service.revision == 0
    assert await stored_rows(db) == []

    integration = make_integration(service)
    await declare_temp(integration)
    await integration.commit_declarations()
    await integration.on_shutdown()

    counts = await make_integration(service).commit_declarations()
    assert counts is not None
    assert counts.removed == 1
    assert await stored_rows(db) == []


async def test_attributes_are_copied_in_and_out(db: DatabaseService) -> None:
    service = await start_service(db)
    temp = await committed_temp(service)

    attributes: dict[str, Any] = {"history": [1]}
    await temp.set(1, attributes=attributes)
    attributes["history"].append(2)
    temp.attributes["history"].append(3)  # pyright: ignore[reportIndexIssue]

    assert temp.attributes == {"history": [1]}
    await temp.set(1, attributes={"history": [1, 2]})
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "1", '{"history": [1, 2]}')]


async def test_prune_failure_fails_startup(db: DatabaseService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integration_store, "prune_and_load", fail_with_disk_error)
    with pytest.raises(aiosqlite.OperationalError):
        await start_service(db)


async def test_set_racing_the_commit_lands_after_it(db: DatabaseService) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 1)

    await asyncio.gather(integration.commit_declarations(), temp.set(2))

    assert temp.value == 2
    assert await stored_rows(db) == [("kitchen", "temp", "sensor", "2", "{}")]


async def test_set_waiting_on_a_commit_that_fails_raises_closed(db: DatabaseService) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 1)
    service.persist_instance_set = fail_with_disk_error  # pyright: ignore[reportAttributeAccessIssue]

    commit, write = await asyncio.gather(integration.commit_declarations(), temp.set(2), return_exceptions=True)

    assert isinstance(commit, aiosqlite.OperationalError)
    assert isinstance(write, IntegrationHandleClosedError)


async def test_set_waiting_on_a_commit_when_the_instance_stops_raises_closed(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 1)
    entered, release = gate(service, "persist_instance_set", monkeypatch)

    commit = asyncio.create_task(integration.commit_declarations())
    await asyncio.wait_for(entered.wait(), timeout=1)
    write = asyncio.create_task(temp.set(2))
    await asyncio.sleep(0)
    await integration.on_shutdown()
    release.set()
    await commit

    with pytest.raises(IntegrationHandleClosedError):
        await write
    assert [entity.state.value for entity in service.entities("my_app", "kitchen")] == [1]


async def test_read_during_the_commit_returns_the_value_set_during_init(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    temp = await declare_temp(integration, 21.5)
    entered, release = gate(service, "persist_instance_set", monkeypatch)

    commit = asyncio.create_task(integration.commit_declarations())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert temp.value == 21.5
    release.set()
    await commit
    assert temp.value == 21.5


async def test_declaration_is_recorded_only_once_its_listener_is_registered(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)
    await declare_temp(integration)
    subscription = MagicMock()

    async def registered(*_: Any) -> Any:
        return subscription

    monkeypatch.setattr(integration, "register_listener", registered)
    entered, release = gate(integration, "register_listener", monkeypatch)
    adding = asyncio.create_task(integration.add_button("feed", name="Feed", on_press=async_noop))
    await asyncio.wait_for(entered.wait(), timeout=1)

    await integration.commit_declarations()
    release.set()
    with pytest.raises(IntegrationDeclarationClosedError):
        await adding

    assert [entity.declaration.key for entity in service.entities("my_app", "kitchen")] == ["temp"]
    subscription.cancel.assert_called_once_with()


async def test_concurrent_declarations_of_one_key_reject_the_second(
    db: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = await start_service(db)
    integration = make_integration(service)

    async def registered(*_: Any) -> Any:
        await asyncio.sleep(0)
        return MagicMock()

    monkeypatch.setattr(integration, "register_listener", registered)
    first = integration.add_button("feed", name="Feed", on_press=async_noop)
    second = integration.add_button("feed", name="Feed", on_press=async_noop)

    results = await asyncio.gather(first, second, return_exceptions=True)

    assert sum(isinstance(result, ValueError) for result in results) == 1
    await integration.commit_declarations()
    assert [entity.declaration.key for entity in service.entities("my_app", "kitchen")] == ["feed"]

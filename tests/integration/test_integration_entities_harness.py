"""App-declared buttons, switches and sensors through AppTestHarness (spec 157)."""

import pytest
from hassette_wire import ExecutionMode

from hassette import (
    App,
    AppConfig,
    AppSync,
    D,
    IntegrationButton,
    IntegrationDeclarationClosedError,
    IntegrationHandleClosedError,
    IntegrationSensor,
    IntegrationSwitch,
)
from hassette.integration.declarations import EntityState
from hassette.testing import AppTestHarness


class EntitiesConfig(AppConfig):
    """Config for the entity test apps."""


class EntitiesApp(App[EntitiesConfig]):
    """Declares one of each platform; sets the sensor and the switch during init."""

    feed: IntegrationButton
    show: IntegrationSwitch
    temp: IntegrationSensor

    async def on_initialize(self) -> None:
        self.presses = 0
        self.toggles: list[bool] = []
        self.init_reads: list[object] = []
        self.feed = await self.integration.add_button("feed", name="Feed", on_press=self.on_feed)
        self.show = await self.integration.add_switch("show", name="Show", on_toggle=self.on_show)
        self.temp = await self.integration.add_sensor("temp", name="Temp", unit="°C", device_class="temperature")
        self.init_reads.append(self.temp.value)
        await self.temp.set(21.5, attributes={"source": "init"})
        self.init_reads.append(self.temp.value)

    async def on_feed(self) -> None:
        self.presses += 1

    async def on_show(self, on: D.SwitchCommand) -> None:
        self.toggles.append(on)
        if self.app_config.instance_name != "forgetful":
            await self.show.set(on)


def state_of(harness: AppTestHarness, key: str) -> EntityState:
    return next(entity.state for entity in harness.integration_entities if entity.declaration.key == key)


async def test_declarations_and_init_values_are_committed() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        assert [entity.declaration.key for entity in harness.integration_entities] == ["feed", "show", "temp"]
        assert state_of(harness, "temp") == EntityState(21.5, {"source": "init"})
        assert state_of(harness, "show") == EntityState(False, {})
        assert harness.app.init_reads == [None, 21.5]


async def test_button_press_runs_handler_registered_as_named_listener() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        await harness.simulate_button_press("feed")
        assert harness.app.presses == 1
        names = {listener.identity.name for listener in harness.bus.get_listeners()}
        assert {"integration.button.feed", "integration.switch.show"} <= names


async def test_switch_toggle_passes_value_and_handler_sets_state() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        await harness.simulate_switch_toggle("show", True)
        assert harness.app.toggles == [True]
        assert harness.app.show.is_on
        assert state_of(harness, "show").value is True


async def test_switch_keeps_state_when_handler_does_not_set_it() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "forgetful"}) as harness:
        await harness.simulate_switch_toggle("show", True)
        assert harness.app.toggles == [True]
        assert not harness.app.show.is_on


async def test_simulating_an_undeclared_key_raises() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        with pytest.raises(ValueError, match="declared no switch"):
            await harness.simulate_switch_toggle("feed", True)


async def test_a_press_after_the_instance_stopped_raises() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        await harness.app.shutdown()
        with pytest.raises(RuntimeError, match="isn't running"):
            await harness.simulate_button_press("feed")
        with pytest.raises(RuntimeError, match="isn't running"):
            await harness.simulate_switch_toggle("show", True)
        assert harness.app.presses == 0
        assert harness.app.toggles == []


async def test_declaring_after_the_commit_raises() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        with pytest.raises(IntegrationDeclarationClosedError):
            await harness.app.integration.add_sensor("late", name="Late")


async def test_set_replaces_attributes_and_identical_set_writes_nothing() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        service = harness.require_harness().integration_service
        await harness.app.temp.set(22, attributes={"x": 1})
        revision = service.revision
        await harness.app.temp.set(22, attributes={"x": 1})
        assert service.revision == revision
        await harness.app.temp.set(23)
        assert service.revision == revision + 1
        assert harness.app.temp.state == EntityState(23, {})


async def test_rejected_value_leaves_state_unchanged() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        with pytest.raises(ValueError, match="numeric sensor"):
            await harness.app.temp.set("hot")
        with pytest.raises(ValueError, match="takes a bool"):
            await harness.app.show.set(1)  # pyright: ignore[reportArgumentType]
        assert harness.app.temp.value == 21.5


async def test_set_after_the_instance_stopped_raises() -> None:
    async with AppTestHarness(EntitiesApp, config={"instance_name": "entities"}) as harness:
        temp = harness.app.temp
        await harness.app.shutdown()
        with pytest.raises(IntegrationHandleClosedError):
            await temp.set(30)
        with pytest.raises(IntegrationHandleClosedError):
            _ = temp.value


class BadDeclarationsApp(App[EntitiesConfig]):
    """Records the error each invalid declaration raises at the call."""

    async def on_initialize(self) -> None:
        self.errors: list[str] = []
        await self.integration.add_sensor("dup", name="Dup")
        for call in (
            lambda: self.integration.add_button("dup", name="Dup", on_press=self.noop),
            lambda: self.integration.add_button("Bad-Key", name="Bad", on_press=self.noop),
            lambda: self.integration.add_switch("s", name="S", on_toggle=self.noop, default_entity_id="button.s"),
            lambda: self.integration.add_sensor("e", name="E", device_class="enum"),
        ):
            try:
                call()
            except ValueError as exc:
                self.errors.append(str(exc))

    async def noop(self) -> None:
        pass


async def test_invalid_declarations_raise_at_the_call() -> None:
    async with AppTestHarness(BadDeclarationsApp, config={"instance_name": "bad"}) as harness:
        errors = harness.app.errors
        assert len(errors) == 4
        assert "already declared" in errors[0]
        assert "Bad-Key" in errors[1]
        assert "default_entity_id" in errors[2]
        assert "needs options" in errors[3]
        assert [entity.declaration.key for entity in harness.integration_entities] == ["dup"]


class SyncEntitiesApp(AppSync[EntitiesConfig]):
    """Declares and sets through the sync facade."""

    def on_initialize_sync(self) -> None:
        self.mode = self.integration.sync.add_sensor("mode", name="Mode", device_class="enum", options=["a", "b"])
        self.integration.sync.set(self.mode, "b")


async def test_sync_facade_declares_and_sets() -> None:
    async with AppTestHarness(SyncEntitiesApp, config={"instance_name": "sync_entities"}) as harness:
        assert state_of(harness, "mode").value == "b"


class QueuedButtonApp(App[EntitiesConfig]):
    """Declares a button with a non-default execution mode."""

    async def on_initialize(self) -> None:
        self.feed = await self.integration.add_button("feed", name="Feed", on_press=self.on_feed, mode="queued")

    async def on_feed(self) -> None:
        pass


async def test_button_mode_reaches_its_listener() -> None:
    async with AppTestHarness(QueuedButtonApp, config={"instance_name": "queued"}) as harness:
        assert harness.app.feed.subscription.listener.options.mode is ExecutionMode.QUEUED

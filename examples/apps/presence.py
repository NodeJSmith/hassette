# compare to: https://github.com/AppDaemon/appdaemon/blob/dev/conf/example_apps/presence.py

import typing

from hassette import App, AppConfig, states
from hassette import dependencies as D
from hassette.const.misc import FalseySentinel

if typing.TYPE_CHECKING:
    from sound import Sound


class PresenceAppConfig(AppConfig):
    notify: str | None = None
    day_scene_off: str | None = None
    day_scene_absent: str | None = None

    night_scene_absent: str | None = None
    night_scene_present: str | None = None

    input_select: str | None = None
    vacation: str | None = None
    announce: str | None = None
    volume: float = 6


class Presence(App[PresenceAppConfig]):
    async def on_initialize(self) -> None:
        """Use the `on_initialize` lifecycle hook to set up the app."""
        # Subscribe to presence changes

        self.bus.on_state_change("device_tracker.*", handler=self.presence_change)
        self.bus.on_state_change(
            "group.all_devices", handler=self.everyone_left, changed_from="home", changed_to="not_home"
        )
        self.bus.on_state_change(
            "group.all_devices", handler=self.someone_home, changed_from="not_home", changed_to="home"
        )
        await self.api.set_state("sensor.andrew_tracker", state="away")
        await self.api.set_state("sensor.wendy_tracker", state="away")

    async def presence_change(
        self,
        new_state: D.StateNew[states.DeviceTrackerState],
        old_value: D.StateValueOld,
        new_value: D.StateValueNew,
        entity_id: D.EntityId,
    ):
        """Handle presence changes using dependency injection.

        DI automatically extracts:
        - new_state: Full device tracker state
        - old_value/new_value: State values (e.g., "home", "not_home")
        - entity_id: The device tracker entity ID
        """
        assert not isinstance(entity_id, FalseySentinel), "Entity ID must be provided"
        person = new_state.attributes.friendly_name or entity_id

        tracker_entity = f"sensor.{person.lower()}_tracker"

        new = new_value
        old = old_value
        announce_app: Sound | None = self.hassette.get_app("Sound")  # pyright: ignore[reportAssignmentType]

        await self.api.set_state(tracker_entity, state=new)
        if old != new:
            if new == "not_home":
                place = "is away"
                if self.app_config.announce and self.app_config.announce.find(person) != -1:
                    if not announce_app:
                        self.logger.error("Sound app not found, cannot announce")
                        return

                    await announce_app.tts(f"{person} just left", self.app_config.volume, 3)
            elif new == "home":
                place = "arrived home"
                if self.app_config.announce and self.app_config.announce.find(person) != -1:
                    if not announce_app:
                        self.logger.error("Sound app not found, cannot announce")
                        return
                    await announce_app.tts(f"{person} arrived home", self.app_config.volume, 3)
            else:
                place = f"is at {new}"
            message = f"{person} {place}"
            self.logger.info(message)
            if self.app_config.notify:
                await self.api.call_service("notify", "my_mobile_phone", message=message)

    async def everyone_left(self):
        self.logger.info("Everyone left")
        valid_modes = (self.app_config.input_select or "").split(",")
        input_select = valid_modes.pop(0)

        # Use state cache instead of API call
        input_select_state = self.states.input_select.get(input_select)
        if input_select_state and input_select_state.value in valid_modes:
            if self.app_config.day_scene_absent:
                await self.api.turn_on(self.app_config.day_scene_absent)
        else:
            if self.app_config.night_scene_absent:
                await self.api.turn_on(self.app_config.night_scene_absent)

    async def someone_home(self):
        self.logger.info("Someone came home")
        if self.app_config.vacation:
            await self.api.set_state(self.app_config.vacation, state="off")
        valid_modes = (self.app_config.input_select or "").split(",")
        input_select = valid_modes.pop(0)

        # Use state cache instead of API call
        input_select_state = self.states.input_select.get(input_select)
        if input_select_state and input_select_state.value in valid_modes:
            if self.app_config.day_scene_off:
                await self.api.turn_on(self.app_config.day_scene_off)
        else:
            if self.app_config.night_scene_present:
                await self.api.turn_on(self.app_config.night_scene_present)

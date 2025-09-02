from hassette.core.apps import App, AppConfig
from hassette.models.events import StateChangeEvent
from hassette.models.states import DeviceTrackerState, PersonState


class PresenceAppConfig(AppConfig):
    notify: str | None = None
    day_scene_off: str | None = None
    day_scene_absent: str | None = None

    night_scene_absent: str | None = None
    night_scene_present: str | None = None

    input_select: str | None = None
    vacation: str | None = None
    announce: str | None = None
    volume: int | None = None


class Presence(App[PresenceAppConfig]):
    async def initialize(self):
        # Subscribe to presence changes

        self.bus.on_entity("device_tracker.*", handler=self.presence_change)
        self.bus.on_entity("group.all_devices", handler=self.everyone_left, changed_from="home", changed_to="not_home")
        self.bus.on_entity("group.all_devices", handler=self.someone_home, changed_from="not_home", changed_to="home")
        await self.api.set_state("sensor.andrew_tracker", state="away")
        await self.api.set_state("sensor.wendy_tracker", state="away")

    async def presence_change(self, event: StateChangeEvent[DeviceTrackerState]):
        person = await self.api.get_attribute(event.payload.data.entity_id, attribute="friendly_name")
        person_state = await self.api.get_state(event.payload.data.entity_id, PersonState)
        if person_state.attributes and person_state.attributes.friendly_name:
            person = person_state.attributes.friendly_name

        tracker_entity = f"sensor.{person.lower()}_tracker"

        new = event.payload.data.new_state_value
        old = event.payload.data.old_state_value

        await self.api.set_state(tracker_entity, state=event.payload.data.new_state_value)
        if old != new:
            if new == "not_home":
                place = "is away"
                if self.app_config.announce and self.app_config.announce.find(person) != -1:
                    self.logger.error("We currently do not implement `get_app` logic")
                    # self.announce = self.get_app("Sound")
                    # self.announce.tts(f"{person} just left", self.app_config.volume, 3)
            elif new == "home":
                place = "arrived home"
                if self.app_config.announce and self.app_config.announce.find(person) != -1:
                    self.logger.error("We currently do not implement `get_app` logic")
                    # self.announce = self.get_app("Sound")
                    # self.announce.tts(f"{person} arrived home", self.app_config.volume, 3)
            else:
                place = f"is at {new}"
            message = f"{person} {place}"
            self.logger.info(message)
            if self.app_config.notify:
                await self.api.call_service(
                    "notify",
                    "notify",
                    target={"entity_id": self.app_config.notify},
                    message=message,
                )

    async def everyone_left(self, event: StateChangeEvent[DeviceTrackerState]):
        self.logger.info("Everyone left")
        valid_modes = (self.app_config.input_select or "").split(",")
        input_select = valid_modes.pop(0)
        if (await self.api.get_state_value(input_select)) in valid_modes:
            if self.app_config.day_scene_absent:
                await self.api.turn_on(self.app_config.day_scene_absent)
        else:
            if self.app_config.night_scene_absent:
                await self.api.turn_on(self.app_config.night_scene_absent)

    async def someone_home(self, event: StateChangeEvent[DeviceTrackerState]):
        self.logger.info("Someone came home")
        if self.app_config.vacation:
            await self.api.set_state(self.app_config.vacation, state="off")
        valid_modes = (self.app_config.input_select or "").split(",")
        input_select = valid_modes.pop(0)
        if (await self.api.get_state_value(input_select)) in valid_modes:
            if self.app_config.day_scene_off:
                await self.api.turn_on(self.app_config.day_scene_off)
        else:
            if self.app_config.night_scene_present:
                await self.api.turn_on(self.app_config.night_scene_present)

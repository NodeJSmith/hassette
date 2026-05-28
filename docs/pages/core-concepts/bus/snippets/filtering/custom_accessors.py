from hassette import A, App, AppConfig, P
from hassette.bus.event import RawCallServiceEvent, RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Only handle turn_on calls targeting a specific entity
        entity_match = P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")
        self.bus.on_call_service("light.turn_on", handler=self.on_living_room_on, where=entity_match)

        # Check a nested attribute value using a dotted path
        city_match = P.ValueIs(
            source=A.get_path("payload.data.new_state.attributes.geolocation.locality"),
            condition="San Francisco",
        )
        self.bus.on_state_change("sensor.my_device_location", handler=self.on_location_change, changed_to=city_match)

    async def on_living_room_on(self, event: RawCallServiceEvent) -> None: ...
    async def on_location_change(self, event: RawStateChangeEvent) -> None: ...

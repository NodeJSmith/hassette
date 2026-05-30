from hassette import A, App, AppConfig, P
from hassette.events import CallServiceEvent, RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Only handle turn_on calls targeting a specific entity
        entity_match = P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")
        await self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_living_room_on, where=entity_match, name="living_room_turn_on")

        # Check a nested attribute value using a dotted path
        city_match = P.ValueIs(
            source=A.get_path("payload.data.new_state.attributes.geolocation.locality"),
            condition="San Francisco",
        )
        await self.bus.on_state_change("sensor.my_device_location", handler=self.on_location_change, changed_to=city_match, name="device_location")

    async def on_living_room_on(self, event: CallServiceEvent) -> None: ...
    async def on_location_change(self, event: RawStateChangeEvent) -> None: ...

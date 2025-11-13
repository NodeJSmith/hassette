from hassette import App


class BasicSubscriptionsExample(App):
    async def on_initialize(self):
        # Entity state changes
        self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, changed_to="on")

        # Attribute changes
        self.bus.on_attribute_change("climate.living_room", "temperature", handler=self.on_temp_change)

        # Service calls
        self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)

        # Home Assistant lifecycle events (built-in shortcuts)
        self.bus.on_homeassistant_restart(handler=self.on_restart)

        # Component loaded events
        self.bus.on_component_loaded("hue", handler=self.on_hue_loaded)

        # Service registered events
        self.bus.on_service_registered(domain="notify", handler=self.on_notify_service_added)

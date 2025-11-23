from hassette import App, states


class StatesExample(App):
    async def states_example(self):
        # PREFERRED: Use state cache for instant access (no API call)
        # Access all entities
        all_states = self.states.all

        # Target a specific device with typed model (no await needed)
        climate = self.states.climate.get("climate.living_room")
        if climate and climate.attributes.hvac_action == "heating":
            self.logger.debug("Living room is warming up (%.1f)", climate.attributes.current_temperature)

        # Access state value directly
        outdoor_sensor = self.states.sensor.get("sensor.outdoor_temp")
        temperature = outdoor_sensor.value if outdoor_sensor else None

        # ALTERNATIVE: Force fresh read from API (rare, requires await)
        fresh_climate = await self.api.get_state("climate.living_room", states.ClimateState)
        self.logger.debug("Fresh HVAC action: %s", fresh_climate.attributes.hvac_action)

        return all_states, climate, temperature

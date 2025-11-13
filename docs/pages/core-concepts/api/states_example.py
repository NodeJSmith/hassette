from hassette import App, states


class StatesExample(App):
    async def states_example(self):
        # Bulk fetch every entity as a typed state union
        all_states = await self.api.get_states()

        # Target a specific device with a concrete model
        climate = await self.api.get_state("climate.living_room", states.ClimateState)
        if climate.attributes.hvac_action == "heating":
            self.logger.debug("Living room is warming up (%.1f°C)", climate.attributes.current_temperature)

        # Raw access
        temperature = await self.api.get_state_value("sensor.outdoor_temp")
        return all_states, climate, temperature

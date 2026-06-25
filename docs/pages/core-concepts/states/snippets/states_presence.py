from hassette import App


class PresenceApp(App):
    async def on_initialize(self):
        # Quantifiers read the person domain (device_tracker fallback) from the
        # local cache — synchronous, no await, no API call.
        if self.states.nobody_home():
            await self.api.turn_off("climate.house", domain="climate")

        if self.states.anybody_home():
            await self.api.turn_on("light.porch", domain="light")

        if self.states.everybody_home():
            self.logger.info("The whole household is home")

        # is_home checks a single entity by full entity ID.
        if self.states.is_home("person.jessica"):
            await self.api.turn_on("light.office", domain="light")

from hassette import App


class StateApp(App):
    async def on_initialize(self):
        # Access by domain
        light = self.states.light.get("light.kitchen")

        # Access attributes safely
        if light:
            print(light.attributes.brightness)

        # if you know the entity exists you can access it directly using dictionary-style access
        self.states.sensor["temperature"]

        # notice how you didn't need to provide the full entity ID, just the entity name
        # this is because the domain is already known from the property (`self.states.sensor`), so only the entity name
        # is needed

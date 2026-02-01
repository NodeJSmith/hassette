from hassette import App


class StateApp(App):
    async def on_initialize(self):
        # Access by domain
        light = self.states.light.get("light.kitchen")

        # Access attributes safely
        if light:
            print(light.attributes.brightness)

        # if you know the entity exists you can access it
        # directly using dictionary-style access
        self.states.sensor["temperature"]

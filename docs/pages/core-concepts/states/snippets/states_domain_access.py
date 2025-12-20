from hassette import App


class StateApp(App):
    async def on_initialize(self):
        # Access by domain
        light = self.states.light.get("light.kitchen")
        sensor = self.states.sensor.get("sensor.temperature")

        # Access attributes safely
        if light:
            print(light.attributes.brightness)

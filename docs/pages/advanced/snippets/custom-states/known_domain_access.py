from hassette import App


class MyApp(App):
    async def on_initialize(self):
        # Known domains (autocomplete works)
        for entity_id, light in self.states.light:
            print(light.attributes.brightness)

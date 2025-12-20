from hassette import App, states


class GenericApp(App):
    async def on_initialize(self):
        # Generic get (returns BaseState if model not specified)
        state = self.states.get("group.all_lights")

        # Typed generic get
        calendar = self.states.get[states.CalendarState]("calendar.work")
        if calendar:
            print(calendar.state)

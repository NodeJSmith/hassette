from hassette import App, states


class GenericApp(App):
    async def on_initialize(self):
        # Typed generic get
        calendar = self.states[states.CalendarState].get("calendar.work")
        if calendar:
            print(calendar.value)

from hassette import App


class TempApp(App):
    async def on_initialize(self):
        # Trigger if temperature behaves logically (numeric check)
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            # changed_to expects a value or predicate, lambda x: x > 25.0 works if passed as value for checking against new state
            changed_to=lambda x: x > 25.0,
        )

    async def on_temp_change(self, event):
        pass

from hassette import App, D, states


class TempApp(App):
    async def on_temp_change(
        self,
        new: D.StateNew[states.SensorState],
        old: D.MaybeStateOld[states.SensorState],
    ):
        if old and old.value and new.value:
            delta = float(new.value) - float(old.value)
            self.logger.info(
                "Temperature moved %.1f°F", delta
            )

from hassette import App, D, states


class LightApp(App):
    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
        context: D.EventContext,
    ):
        self.logger.info(
            "Light %s changed by user %s",
            new_state.entity_id,
            context.user_id or "system",
        )

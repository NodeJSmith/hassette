from hassette import App, D, states


class ClimateApp(App):
    async def on_climate_change(
        self,
        new: D.StateNew[states.ClimateState],
        entity_id: D.EntityId,
        context: D.EventContext,
    ):
        temp = new.attributes.current_temperature
        self.logger.info(
            "%s temperature: %s (user: %s)",
            entity_id,
            temp,
            context.user_id or "system",
        )

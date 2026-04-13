from hassette import App, D, states


class ClimateApp(App):
    async def on_climate_change(
        self,
        new_state: D.StateNew[states.ClimateState],
        old_state: D.MaybeStateOld[states.ClimateState],
        entity_id: D.EntityId,
        context: D.EventContext,
    ):
        old_temp = old_state.attributes.current_temperature if old_state else None
        new_temp = new_state.attributes.current_temperature

        if old_temp != new_temp:
            self.logger.info(
                "Climate %s temperature changed: %s -> %s (user: %s)",
                entity_id,
                old_temp,
                new_temp,
                context.user_id or "system",
            )

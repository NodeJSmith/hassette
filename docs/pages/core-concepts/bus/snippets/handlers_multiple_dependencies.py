from hassette import App, states
from hassette import dependencies as D


class ClimateApp(App):
    async def on_climate_change(
        self,
        new_state: D.StateNew[states.ClimateState],
        old_state: D.MaybeStateOld[states.ClimateState],
        entity_id: D.EntityId,
    ):
        old_temp = old_state.attributes.current_temperature if old_state else "N/A"
        new_temp = new_state.attributes.current_temperature
        self.logger.info(
            "Climate %s temperature changed: %s -> %s",
            entity_id,
            old_temp,
            new_temp,
        )

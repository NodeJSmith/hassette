from hassette import AppSync
from hassette.models import entities


class CoverApp(AppSync):
    def on_initialize_sync(self) -> None:
        # --8<-- [start:entity_sync_domain_action]
        cover = self.api.sync.get_entity(
            "cover.living_room", entities.CoverEntity
        )
        cover.sync.open_cover()
        cover.sync.set_cover_position(position=60)
        # --8<-- [end:entity_sync_domain_action]


class ClimateApp(AppSync):
    def on_initialize_sync(self) -> None:
        # --8<-- [start:entity_sync_climate]
        climate = self.api.sync.get_entity(
            "climate.bedroom", entities.ClimateEntity
        )
        climate.sync.set_temperature(temperature=21.0)
        # --8<-- [end:entity_sync_climate]

import asyncio

from hassette import App, AppConfig, P


class WaitForApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:basic]
        event = await self.bus.wait_for(
            "hass.event.state_changed.light.kitchen",
            where=P.StateTo("on"),
            timeout=5,
        )
        # --8<-- [end:basic]
        self.logger.info("Kitchen light turned on: %s", event.topic)

    async def turn_on_and_confirm(self) -> None:
        # --8<-- [start:arm_before_fire]
        wait_task = asyncio.create_task(
            self.bus.wait_for(
                "hass.event.state_changed.light.kitchen",
                where=P.StateTo("on"),
                timeout=5,
            )
        )
        await self.api.call_service(
            "light", "turn_on", entity_id="light.kitchen"
        )
        event = await wait_task
        # --8<-- [end:arm_before_fire]
        self.logger.info("Confirmed on: %s", event.topic)

    async def play_and_confirm_idle(self) -> None:
        entity_id = "media_player.living_room"

        # --8<-- [start:two_stage]
        started = asyncio.create_task(
            self.bus.wait_for(
                f"hass.event.state_changed.{entity_id}",
                where=~P.StateTo("idle"),
                timeout=5,
            )
        )
        await self.api.call_service(
            "media_player", "media_play", entity_id=entity_id
        )
        await started

        await self.bus.wait_for(
            f"hass.event.state_changed.{entity_id}",
            where=P.StateTo("idle"),
            timeout=30,
        )
        # --8<-- [end:two_stage]
        self.logger.info("Playback finished, %s is idle again", entity_id)

# method taken from: https://github.com/AppDaemon/appdaemon/blob/dev/conf/example_apps/sound.py
# but overall app is not meant to match

import asyncio

from hassette import App, AppConfig


class SoundAppConfig(AppConfig):
    player: str = "media_player.living_room_echo"


class Sound(App[SoundAppConfig]):
    async def tts(self, text: str, volume: float, length: float):
        # Save current volume
        current_volume = await self.api.get_attribute(self.app_config.player, attribute="volume_level")

        # Set to the desired volume
        await self.api.call_service("volume_set", "media_player", entity_id=self.app_config.player, volume_level=volume)

        # Call TTS service
        await self.api.call_service("amazon_polly_say", "tts", entity_id=self.app_config.player, message=text)

        # Wait for the length of the message
        await asyncio.sleep(length)

        # Restore original volume
        await self.api.call_service(
            "volume_set", "media_player", entity_id=self.app_config.player, volume_level=current_volume
        )

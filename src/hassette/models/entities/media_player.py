from typing import Any, Literal

from hassette.models.states import MediaPlayerState
from hassette.models.states.media_player import MediaPlayerAttributes

from .base import BaseEntity

Enqueue = Literal["play", "next", "add", "replace"]

Repeat = Literal["off", "all", "one"]


class MediaPlayerEntity(BaseEntity[MediaPlayerState, str]):
    @property
    def attributes(self) -> MediaPlayerAttributes:
        return self.state.attributes

    async def turn_on(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    async def volume_up(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="volume_up",
            target={"entity_id": self.entity_id},
        )

    async def volume_down(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="volume_down",
            target={"entity_id": self.entity_id},
        )

    async def volume_mute(
        self,
        *,
        is_volume_muted: bool,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="volume_mute",
            target={"entity_id": self.entity_id},
            is_volume_muted=is_volume_muted,
        )

    async def volume_set(
        self,
        *,
        volume_level: float,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="volume_set",
            target={"entity_id": self.entity_id},
            volume_level=volume_level,
        )

    async def media_play_pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_play_pause",
            target={"entity_id": self.entity_id},
        )

    async def media_play(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_play",
            target={"entity_id": self.entity_id},
        )

    async def media_pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_pause",
            target={"entity_id": self.entity_id},
        )

    async def media_stop(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_stop",
            target={"entity_id": self.entity_id},
        )

    async def media_next_track(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_next_track",
            target={"entity_id": self.entity_id},
        )

    async def media_previous_track(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_previous_track",
            target={"entity_id": self.entity_id},
        )

    async def media_seek(
        self,
        *,
        seek_position: float,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="media_seek",
            target={"entity_id": self.entity_id},
            seek_position=seek_position,
        )

    async def play_media(
        self,
        *,
        media: dict[str, Any],
        announce: bool | None = None,
        enqueue: Enqueue | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="play_media",
            target={"entity_id": self.entity_id},
            media=media,
            announce=announce,
            enqueue=enqueue,
        )

    async def browse_media(
        self,
        *,
        media_content_id: str | None = None,
        media_type: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="browse_media",
            target={"entity_id": self.entity_id},
            media_content_id=media_content_id,
            media_type=media_type,
        )

    async def search_media(
        self,
        *,
        search_query: str,
        media_content_id: str | None = None,
        media_filter_classes: str | None = None,
        media_type: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="search_media",
            target={"entity_id": self.entity_id},
            search_query=search_query,
            media_content_id=media_content_id,
            media_filter_classes=media_filter_classes,
            media_type=media_type,
        )

    async def select_source(
        self,
        *,
        source: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_source",
            target={"entity_id": self.entity_id},
            source=source,
        )

    async def select_sound_mode(
        self,
        *,
        sound_mode: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity_id},
            sound_mode=sound_mode,
        )

    async def clear_playlist(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="clear_playlist",
            target={"entity_id": self.entity_id},
        )

    async def shuffle_set(
        self,
        *,
        shuffle: bool,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="shuffle_set",
            target={"entity_id": self.entity_id},
            shuffle=shuffle,
        )

    async def repeat_set(
        self,
        *,
        repeat: Repeat,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="repeat_set",
            target={"entity_id": self.entity_id},
            repeat=repeat,
        )

    async def join(
        self,
        *,
        group_members: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="join",
            target={"entity_id": self.entity_id},
            group_members=group_members,
        )

    async def unjoin(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="unjoin",
            target={"entity_id": self.entity_id},
        )

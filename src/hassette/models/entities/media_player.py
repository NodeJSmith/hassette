from collections.abc import Coroutine
from typing import Any, Literal, cast

from hassette.models.states import MediaPlayerState
from hassette.models.states.media_player import MediaPlayerAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Enqueue = Literal["play", "next", "add", "replace"]

Repeat = Literal["off", "all", "one"]


class MediaPlayerEntity(BaseEntity[MediaPlayerState, str]):
    @property
    def attributes(self) -> MediaPlayerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "MediaPlayerEntitySyncFacade":
        if self._sync is None:
            self._sync = MediaPlayerEntitySyncFacade(entity=self)
        return cast("MediaPlayerEntitySyncFacade", self._sync)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def volume_up(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_up",
            target={"entity_id": self.entity_id},
        )

    def volume_down(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_down",
            target={"entity_id": self.entity_id},
        )

    def volume_mute(
        self,
        *,
        is_volume_muted: bool,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_mute",
            target={"entity_id": self.entity_id},
            is_volume_muted=is_volume_muted,
        )

    def volume_set(
        self,
        *,
        volume_level: float,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_set",
            target={"entity_id": self.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_play_pause",
            target={"entity_id": self.entity_id},
        )

    def media_play(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_play",
            target={"entity_id": self.entity_id},
        )

    def media_pause(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_pause",
            target={"entity_id": self.entity_id},
        )

    def media_stop(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_stop",
            target={"entity_id": self.entity_id},
        )

    def media_next_track(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_next_track",
            target={"entity_id": self.entity_id},
        )

    def media_previous_track(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_previous_track",
            target={"entity_id": self.entity_id},
        )

    def media_seek(
        self,
        *,
        seek_position: float,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_seek",
            target={"entity_id": self.entity_id},
            seek_position=seek_position,
        )

    def play_media(
        self,
        *,
        media: dict[str, Any],
        announce: bool | None = None,
        enqueue: Enqueue | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="play_media",
            target={"entity_id": self.entity_id},
            media=media,
            announce=announce,
            enqueue=enqueue,
        )

    def browse_media(
        self,
        *,
        media_content_id: str | None = None,
        media_type: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="browse_media",
            target={"entity_id": self.entity_id},
            media_content_id=media_content_id,
            media_type=media_type,
        )

    def search_media(
        self,
        *,
        search_query: str,
        media_content_id: str | None = None,
        media_filter_classes: str | None = None,
        media_type: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="search_media",
            target={"entity_id": self.entity_id},
            search_query=search_query,
            media_content_id=media_content_id,
            media_filter_classes=media_filter_classes,
            media_type=media_type,
        )

    def select_source(
        self,
        *,
        source: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_source",
            target={"entity_id": self.entity_id},
            source=source,
        )

    def select_sound_mode(
        self,
        *,
        sound_mode: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="clear_playlist",
            target={"entity_id": self.entity_id},
        )

    def shuffle_set(
        self,
        *,
        shuffle: bool,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="shuffle_set",
            target={"entity_id": self.entity_id},
            shuffle=shuffle,
        )

    def repeat_set(
        self,
        *,
        repeat: Repeat,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="repeat_set",
            target={"entity_id": self.entity_id},
            repeat=repeat,
        )

    def join(
        self,
        *,
        group_members: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="join",
            target={"entity_id": self.entity_id},
            group_members=group_members,
        )

    def unjoin(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="unjoin",
            target={"entity_id": self.entity_id},
        )


class MediaPlayerEntitySyncFacade(BaseEntitySyncFacade[MediaPlayerState, str]):
    def turn_on(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_up(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_up",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_down(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_down",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_mute(
        self,
        *,
        is_volume_muted: bool,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_mute",
            target={"entity_id": self.entity.entity_id},
            is_volume_muted=is_volume_muted,
        )

    def volume_set(
        self,
        *,
        volume_level: float,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_set",
            target={"entity_id": self.entity.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_play(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play",
            target={"entity_id": self.entity.entity_id},
        )

    def media_pause(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_stop(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_stop",
            target={"entity_id": self.entity.entity_id},
        )

    def media_next_track(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_next_track",
            target={"entity_id": self.entity.entity_id},
        )

    def media_previous_track(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_previous_track",
            target={"entity_id": self.entity.entity_id},
        )

    def media_seek(
        self,
        *,
        seek_position: float,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_seek",
            target={"entity_id": self.entity.entity_id},
            seek_position=seek_position,
        )

    def play_media(
        self,
        *,
        media: dict[str, Any],
        announce: bool | None = None,
        enqueue: Enqueue | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="play_media",
            target={"entity_id": self.entity.entity_id},
            media=media,
            announce=announce,
            enqueue=enqueue,
        )

    def browse_media(
        self,
        *,
        media_content_id: str | None = None,
        media_type: str | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="browse_media",
            target={"entity_id": self.entity.entity_id},
            media_content_id=media_content_id,
            media_type=media_type,
        )

    def search_media(
        self,
        *,
        search_query: str,
        media_content_id: str | None = None,
        media_filter_classes: str | None = None,
        media_type: str | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="search_media",
            target={"entity_id": self.entity.entity_id},
            search_query=search_query,
            media_content_id=media_content_id,
            media_filter_classes=media_filter_classes,
            media_type=media_type,
        )

    def select_source(
        self,
        *,
        source: str,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_source",
            target={"entity_id": self.entity.entity_id},
            source=source,
        )

    def select_sound_mode(
        self,
        *,
        sound_mode: str | None = None,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clear_playlist",
            target={"entity_id": self.entity.entity_id},
        )

    def shuffle_set(
        self,
        *,
        shuffle: bool,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="shuffle_set",
            target={"entity_id": self.entity.entity_id},
            shuffle=shuffle,
        )

    def repeat_set(
        self,
        *,
        repeat: Repeat,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="repeat_set",
            target={"entity_id": self.entity.entity_id},
            repeat=repeat,
        )

    def join(
        self,
        *,
        group_members: str,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="join",
            target={"entity_id": self.entity.entity_id},
            group_members=group_members,
        )

    def unjoin(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="unjoin",
            target={"entity_id": self.entity.entity_id},
        )

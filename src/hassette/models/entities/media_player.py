from collections.abc import Coroutine
from typing import Any, Literal

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
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(MediaPlayerEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.turn_on service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.toggle service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def volume_up(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.volume_up service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_up",
            target={"entity_id": self.entity_id},
        )

    def volume_down(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.volume_down service."""
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
        """Call the media_player.volume_mute service.

        Args:
            is_volume_muted: Defines whether or not it is muted.
        """
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
        """Call the media_player.volume_set service.

        Args:
            volume_level: The volume. 0 is inaudible, 1 is the maximum volume.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="volume_set",
            target={"entity_id": self.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_play_pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_play_pause",
            target={"entity_id": self.entity_id},
        )

    def media_play(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_play service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_play",
            target={"entity_id": self.entity_id},
        )

    def media_pause(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_pause",
            target={"entity_id": self.entity_id},
        )

    def media_stop(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_stop service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_stop",
            target={"entity_id": self.entity_id},
        )

    def media_next_track(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_next_track service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="media_next_track",
            target={"entity_id": self.entity_id},
        )

    def media_previous_track(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.media_previous_track service."""
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
        """Call the media_player.media_seek service.

        Args:
            seek_position: Target position in the currently playing media. The format is platform dependent.
        """
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
        """Call the media_player.play_media service.

        Args:
            media: The media selected to play.
            announce: If the media should be played as an announcement.
            enqueue: If the content should be played now or be added to the queue.
        """
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
        """Call the media_player.browse_media service.

        Args:
            media_content_id: The ID of the content to browse. Integration dependent.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
        """
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
        """Call the media_player.search_media service.

        Args:
            search_query: The term to search for.
            media_content_id: The ID of the content to browse. Integration dependent.
            media_filter_classes: List of media classes to filter the search results by.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
        """
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
        """Call the media_player.select_source service.

        Args:
            source: Name of the source to switch to. Platform dependent.
        """
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
        """Call the media_player.select_sound_mode service.

        Args:
            sound_mode: Name of the sound mode to switch to.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.clear_playlist service."""
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
        """Call the media_player.shuffle_set service.

        Args:
            shuffle: Whether the media should be played in randomized order or not.
        """
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
        """Call the media_player.repeat_set service.

        Args:
            repeat: Whether the media (one or all) should be played in a loop or not.
        """
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
        """Call the media_player.join service.

        Args:
            group_members: The players which will be synced with the playback specified in 'Targets'.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="join",
            target={"entity_id": self.entity_id},
            group_members=group_members,
        )

    def unjoin(self) -> Coroutine[Any, Any, None]:
        """Call the media_player.unjoin service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="unjoin",
            target={"entity_id": self.entity_id},
        )


class MediaPlayerEntitySyncFacade(BaseEntitySyncFacade[MediaPlayerState, str]):
    """Synchronous facade for MediaPlayerEntity service methods."""

    def turn_on(self) -> None:
        """Call the media_player.turn_on service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Call the media_player.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Call the media_player.toggle service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_up(self) -> None:
        """Call the media_player.volume_up service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_up",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_down(self) -> None:
        """Call the media_player.volume_down service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_down",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_mute(
        self,
        *,
        is_volume_muted: bool,
    ) -> None:
        """Call the media_player.volume_mute service synchronously.

        Args:
            is_volume_muted: Defines whether or not it is muted.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_mute",
            target={"entity_id": self.entity.entity_id},
            is_volume_muted=is_volume_muted,
        )

    def volume_set(
        self,
        *,
        volume_level: float,
    ) -> None:
        """Call the media_player.volume_set service synchronously.

        Args:
            volume_level: The volume. 0 is inaudible, 1 is the maximum volume.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_set",
            target={"entity_id": self.entity.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self) -> None:
        """Call the media_player.media_play_pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_play(self) -> None:
        """Call the media_player.media_play service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play",
            target={"entity_id": self.entity.entity_id},
        )

    def media_pause(self) -> None:
        """Call the media_player.media_pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_stop(self) -> None:
        """Call the media_player.media_stop service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_stop",
            target={"entity_id": self.entity.entity_id},
        )

    def media_next_track(self) -> None:
        """Call the media_player.media_next_track service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_next_track",
            target={"entity_id": self.entity.entity_id},
        )

    def media_previous_track(self) -> None:
        """Call the media_player.media_previous_track service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_previous_track",
            target={"entity_id": self.entity.entity_id},
        )

    def media_seek(
        self,
        *,
        seek_position: float,
    ) -> None:
        """Call the media_player.media_seek service synchronously.

        Args:
            seek_position: Target position in the currently playing media. The format is platform dependent.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Call the media_player.play_media service synchronously.

        Args:
            media: The media selected to play.
            announce: If the media should be played as an announcement.
            enqueue: If the content should be played now or be added to the queue.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Call the media_player.browse_media service synchronously.

        Args:
            media_content_id: The ID of the content to browse. Integration dependent.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Call the media_player.search_media service synchronously.

        Args:
            search_query: The term to search for.
            media_content_id: The ID of the content to browse. Integration dependent.
            media_filter_classes: List of media classes to filter the search results by.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
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
    ) -> None:
        """Call the media_player.select_source service synchronously.

        Args:
            source: Name of the source to switch to. Platform dependent.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_source",
            target={"entity_id": self.entity.entity_id},
            source=source,
        )

    def select_sound_mode(
        self,
        *,
        sound_mode: str | None = None,
    ) -> None:
        """Call the media_player.select_sound_mode service synchronously.

        Args:
            sound_mode: Name of the sound mode to switch to.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self) -> None:
        """Call the media_player.clear_playlist service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="clear_playlist",
            target={"entity_id": self.entity.entity_id},
        )

    def shuffle_set(
        self,
        *,
        shuffle: bool,
    ) -> None:
        """Call the media_player.shuffle_set service synchronously.

        Args:
            shuffle: Whether the media should be played in randomized order or not.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="shuffle_set",
            target={"entity_id": self.entity.entity_id},
            shuffle=shuffle,
        )

    def repeat_set(
        self,
        *,
        repeat: Repeat,
    ) -> None:
        """Call the media_player.repeat_set service synchronously.

        Args:
            repeat: Whether the media (one or all) should be played in a loop or not.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="repeat_set",
            target={"entity_id": self.entity.entity_id},
            repeat=repeat,
        )

    def join(
        self,
        *,
        group_members: str,
    ) -> None:
        """Call the media_player.join service synchronously.

        Args:
            group_members: The players which will be synced with the playback specified in 'Targets'.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="join",
            target={"entity_id": self.entity.entity_id},
            group_members=group_members,
        )

    def unjoin(self) -> None:
        """Call the media_player.unjoin service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="unjoin",
            target={"entity_id": self.entity.entity_id},
        )

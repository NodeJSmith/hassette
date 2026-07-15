from collections.abc import Coroutine
from typing import Any

from hassette.models.states import MediaPlayerState
from hassette.models.states.media_player import MediaPlayerAttributes, MediaPlayerEnqueue, MediaType, RepeatMode

from .base import BaseEntity, BaseEntitySyncFacade


class MediaPlayerEntity(BaseEntity[MediaPlayerState, str]):
    @property
    def attributes(self) -> MediaPlayerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "MediaPlayerEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(MediaPlayerEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Turns on the power of a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off the power of a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles a media player on/off."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def volume_up(self) -> Coroutine[Any, Any, None]:
        """Turns up the volume of a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="volume_up",
            target={"entity_id": self.entity_id},
        )

    def volume_down(self) -> Coroutine[Any, Any, None]:
        """Turns down the volume of a media player."""
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
        """Mutes or unmutes a media player.

        Args:
            is_volume_muted: Defines whether or not it is muted.
        """
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
        """Sets the volume level of a media player.

        Args:
            volume_level: The volume. 0 is inaudible, 1 is the maximum volume.
        """
        return self.api.call_service(
            domain=self.domain,
            service="volume_set",
            target={"entity_id": self.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self) -> Coroutine[Any, Any, None]:
        """Toggles play/pause on a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="media_play_pause",
            target={"entity_id": self.entity_id},
        )

    def media_play(self) -> Coroutine[Any, Any, None]:
        """Starts playback on a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="media_play",
            target={"entity_id": self.entity_id},
        )

    def media_pause(self) -> Coroutine[Any, Any, None]:
        """Pauses playback on a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="media_pause",
            target={"entity_id": self.entity_id},
        )

    def media_stop(self) -> Coroutine[Any, Any, None]:
        """Stops playback on a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="media_stop",
            target={"entity_id": self.entity_id},
        )

    def media_next_track(self) -> Coroutine[Any, Any, None]:
        """Selects the next track on a media player."""
        return self.api.call_service(
            domain=self.domain,
            service="media_next_track",
            target={"entity_id": self.entity_id},
        )

    def media_previous_track(self) -> Coroutine[Any, Any, None]:
        """Selects the previous track on a media player."""
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
        """Allows you to go to a different part of the media that is currently playing on a media player.

        Args:
            seek_position: Target position in the currently playing media. The format is platform dependent.
        """
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
        enqueue: MediaPlayerEnqueue | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Starts playing specified media on a media player.

        Args:
            media: The media selected to play.
            announce: If the media should be played as an announcement.
            enqueue: If the content should be played now or be added to the queue.
        """
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
        media_type: MediaType | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Browses the available media.

        Args:
            media_content_id: The ID of the content to browse. Integration dependent.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
        """
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
        media_filter_classes: list[str] | None = None,
        media_type: MediaType | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Searches the available media.

        Args:
            search_query: The term to search for.
            media_content_id: The ID of the content to browse. Integration dependent.
            media_filter_classes: List of media classes to filter the search results by.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
        """
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
        """Sends a media player the command to change the input source.

        Args:
            source: Name of the source to switch to. Platform dependent.
        """
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
        """Selects a specific sound mode of a media player.

        Args:
            sound_mode: Name of the sound mode to switch to.
        """
        return self.api.call_service(
            domain=self.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self) -> Coroutine[Any, Any, None]:
        """Removes all items from a media player's playlist."""
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
        """Enables or disables the shuffle mode of a media player.

        Args:
            shuffle: Whether the media should be played in randomized order or not.
        """
        return self.api.call_service(
            domain=self.domain,
            service="shuffle_set",
            target={"entity_id": self.entity_id},
            shuffle=shuffle,
        )

    def repeat_set(
        self,
        *,
        repeat: RepeatMode,
    ) -> Coroutine[Any, Any, None]:
        """Sets the repeat mode of a media player.

        Args:
            repeat: Whether the media (one or all) should be played in a loop or not.
        """
        return self.api.call_service(
            domain=self.domain,
            service="repeat_set",
            target={"entity_id": self.entity_id},
            repeat=repeat,
        )

    def join(
        self,
        *,
        group_members: list[str],
    ) -> Coroutine[Any, Any, None]:
        """Groups media players together for synchronous playback. Only works on supported multiroom audio systems.

        Args:
            group_members: The players which will be synced with the playback specified in 'Targets'.
        """
        return self.api.call_service(
            domain=self.domain,
            service="join",
            target={"entity_id": self.entity_id},
            group_members=group_members,
        )

    def unjoin(self) -> Coroutine[Any, Any, None]:
        """Removes a media player from a group. Only works on platforms which support player groups."""
        return self.api.call_service(
            domain=self.domain,
            service="unjoin",
            target={"entity_id": self.entity_id},
        )


class MediaPlayerEntitySyncFacade(BaseEntitySyncFacade[MediaPlayerState, str]):
    """Synchronous facade for MediaPlayerEntity service methods."""

    def turn_on(self) -> None:
        """Turns on the power of a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Turns off the power of a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Toggles a media player on/off."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_up(self) -> None:
        """Turns up the volume of a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_up",
            target={"entity_id": self.entity.entity_id},
        )

    def volume_down(self) -> None:
        """Turns down the volume of a media player."""
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
        """Mutes or unmutes a media player.

        Args:
            is_volume_muted: Defines whether or not it is muted.
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
        """Sets the volume level of a media player.

        Args:
            volume_level: The volume. 0 is inaudible, 1 is the maximum volume.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="volume_set",
            target={"entity_id": self.entity.entity_id},
            volume_level=volume_level,
        )

    def media_play_pause(self) -> None:
        """Toggles play/pause on a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_play(self) -> None:
        """Starts playback on a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_play",
            target={"entity_id": self.entity.entity_id},
        )

    def media_pause(self) -> None:
        """Pauses playback on a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_pause",
            target={"entity_id": self.entity.entity_id},
        )

    def media_stop(self) -> None:
        """Stops playback on a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_stop",
            target={"entity_id": self.entity.entity_id},
        )

    def media_next_track(self) -> None:
        """Selects the next track on a media player."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="media_next_track",
            target={"entity_id": self.entity.entity_id},
        )

    def media_previous_track(self) -> None:
        """Selects the previous track on a media player."""
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
        """Allows you to go to a different part of the media that is currently playing on a media player.

        Args:
            seek_position: Target position in the currently playing media. The format is platform dependent.
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
        enqueue: MediaPlayerEnqueue | None = None,
    ) -> None:
        """Starts playing specified media on a media player.

        Args:
            media: The media selected to play.
            announce: If the media should be played as an announcement.
            enqueue: If the content should be played now or be added to the queue.
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
        media_type: MediaType | None = None,
    ) -> None:
        """Browses the available media.

        Args:
            media_content_id: The ID of the content to browse. Integration dependent.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
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
        media_filter_classes: list[str] | None = None,
        media_type: MediaType | None = None,
    ) -> None:
        """Searches the available media.

        Args:
            search_query: The term to search for.
            media_content_id: The ID of the content to browse. Integration dependent.
            media_filter_classes: List of media classes to filter the search results by.
            media_type: The type of the content to browse, such as image, music, TV show, video, episode, channel, or
                playlist.
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
        """Sends a media player the command to change the input source.

        Args:
            source: Name of the source to switch to. Platform dependent.
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
        """Selects a specific sound mode of a media player.

        Args:
            sound_mode: Name of the sound mode to switch to.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="select_sound_mode",
            target={"entity_id": self.entity.entity_id},
            sound_mode=sound_mode,
        )

    def clear_playlist(self) -> None:
        """Removes all items from a media player's playlist."""
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
        """Enables or disables the shuffle mode of a media player.

        Args:
            shuffle: Whether the media should be played in randomized order or not.
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
        repeat: RepeatMode,
    ) -> None:
        """Sets the repeat mode of a media player.

        Args:
            repeat: Whether the media (one or all) should be played in a loop or not.
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
        group_members: list[str],
    ) -> None:
        """Groups media players together for synchronous playback. Only works on supported multiroom audio systems.

        Args:
            group_members: The players which will be synced with the playback specified in 'Targets'.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="join",
            target={"entity_id": self.entity.entity_id},
            group_members=group_members,
        )

    def unjoin(self) -> None:
        """Removes a media player from a group. Only works on platforms which support player groups."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="unjoin",
            target={"entity_id": self.entity.entity_id},
        )

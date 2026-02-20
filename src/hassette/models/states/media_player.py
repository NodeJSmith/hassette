from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import MediaPlayerEntityFeature


class MediaPlayerAttributes(AttributesBase):
    volume_level: float | None = Field(default=None)
    """Volume level of the media player (0..1)."""

    is_volume_muted: bool | None = Field(default=None)
    """Whether volume is currently muted."""

    media_content_id: str | None = Field(default=None)
    """Content ID of current playing media."""

    media_content_type: str | None = Field(default=None)
    """Content type of current playing media."""

    media_duration: int | None = Field(default=None)
    """Duration of current playing media in seconds."""

    media_position: int | None = Field(default=None)
    """Position of current playing media in seconds."""

    media_position_updated_at: str | None = Field(default=None)
    """When media position was last updated (ISO datetime)."""

    media_title: str | None = Field(default=None)
    """Title of current playing media."""

    media_artist: str | None = Field(default=None)
    """Artist of current playing media."""

    media_album_name: str | None = Field(default=None)
    """Album name of current playing media."""

    media_album_artist: str | None = Field(default=None)
    """Album artist of current playing media."""

    media_track: int | None = Field(default=None)
    """Track number of current playing media."""

    media_series_title: str | None = Field(default=None)
    """Series title for current playing media."""

    media_season: str | None = Field(default=None)
    """Season for current playing media."""

    media_episode: str | None = Field(default=None)
    """Episode for current playing media."""

    media_channel: str | None = Field(default=None)
    """Channel currently playing."""

    media_playlist: str | None = Field(default=None)
    """Playlist currently playing."""

    app_id: str | None = Field(default=None)
    """ID of the current running app."""

    app_name: str | None = Field(default=None)
    """Name of the current running app."""

    source: str | None = Field(default=None)
    """Currently selected input source."""

    sound_mode: str | None = Field(default=None)
    """Currently selected sound mode."""

    shuffle: bool | None = Field(default=None)
    """Whether shuffle is enabled."""

    repeat: str | None = Field(default=None)
    """Current repeat mode."""

    group_members: list[str] | None = Field(default=None)
    """List of group member entity IDs."""

    source_list: list[str] | None = Field(default=None)
    """List of available input sources."""

    sound_mode_list: list[str] | None = Field(default=None)
    """List of available sound modes."""

    @property
    def supports_pause(self) -> bool:
        """Whether this media player supports pausing."""
        return self._has_feature(MediaPlayerEntityFeature.PAUSE)

    @property
    def supports_seek(self) -> bool:
        """Whether this media player supports seeking."""
        return self._has_feature(MediaPlayerEntityFeature.SEEK)

    @property
    def supports_volume_set(self) -> bool:
        """Whether this media player supports setting volume."""
        return self._has_feature(MediaPlayerEntityFeature.VOLUME_SET)

    @property
    def supports_volume_mute(self) -> bool:
        """Whether this media player supports muting volume."""
        return self._has_feature(MediaPlayerEntityFeature.VOLUME_MUTE)

    @property
    def supports_previous_track(self) -> bool:
        """Whether this media player supports previous track."""
        return self._has_feature(MediaPlayerEntityFeature.PREVIOUS_TRACK)

    @property
    def supports_next_track(self) -> bool:
        """Whether this media player supports next track."""
        return self._has_feature(MediaPlayerEntityFeature.NEXT_TRACK)

    @property
    def supports_turn_on(self) -> bool:
        """Whether this media player supports turning on."""
        return self._has_feature(MediaPlayerEntityFeature.TURN_ON)

    @property
    def supports_turn_off(self) -> bool:
        """Whether this media player supports turning off."""
        return self._has_feature(MediaPlayerEntityFeature.TURN_OFF)

    @property
    def supports_play_media(self) -> bool:
        """Whether this media player supports playing media."""
        return self._has_feature(MediaPlayerEntityFeature.PLAY_MEDIA)

    @property
    def supports_volume_step(self) -> bool:
        """Whether this media player supports volume stepping."""
        return self._has_feature(MediaPlayerEntityFeature.VOLUME_STEP)

    @property
    def supports_select_source(self) -> bool:
        """Whether this media player supports selecting source."""
        return self._has_feature(MediaPlayerEntityFeature.SELECT_SOURCE)

    @property
    def supports_stop(self) -> bool:
        """Whether this media player supports stopping."""
        return self._has_feature(MediaPlayerEntityFeature.STOP)

    @property
    def supports_clear_playlist(self) -> bool:
        """Whether this media player supports clearing playlist."""
        return self._has_feature(MediaPlayerEntityFeature.CLEAR_PLAYLIST)

    @property
    def supports_play(self) -> bool:
        """Whether this media player supports playing."""
        return self._has_feature(MediaPlayerEntityFeature.PLAY)

    @property
    def supports_shuffle_set(self) -> bool:
        """Whether this media player supports setting shuffle."""
        return self._has_feature(MediaPlayerEntityFeature.SHUFFLE_SET)

    @property
    def supports_select_sound_mode(self) -> bool:
        """Whether this media player supports selecting sound mode."""
        return self._has_feature(MediaPlayerEntityFeature.SELECT_SOUND_MODE)

    @property
    def supports_browse_media(self) -> bool:
        """Whether this media player supports browsing media."""
        return self._has_feature(MediaPlayerEntityFeature.BROWSE_MEDIA)

    @property
    def supports_repeat_set(self) -> bool:
        """Whether this media player supports setting repeat."""
        return self._has_feature(MediaPlayerEntityFeature.REPEAT_SET)

    @property
    def supports_grouping(self) -> bool:
        """Whether this media player supports grouping."""
        return self._has_feature(MediaPlayerEntityFeature.GROUPING)

    @property
    def supports_media_announce(self) -> bool:
        """Whether this media player supports media announcements."""
        return self._has_feature(MediaPlayerEntityFeature.MEDIA_ANNOUNCE)

    @property
    def supports_media_enqueue(self) -> bool:
        """Whether this media player supports media enqueue."""
        return self._has_feature(MediaPlayerEntityFeature.MEDIA_ENQUEUE)

    @property
    def supports_search_media(self) -> bool:
        """Whether this media player supports searching media."""
        return self._has_feature(MediaPlayerEntityFeature.SEARCH_MEDIA)


class MediaPlayerState(StringBaseState):
    """Representation of a Home Assistant media_player state.

    See: https://www.home-assistant.io/integrations/media_player/
    """

    domain: Literal["media_player"]

    attributes: MediaPlayerAttributes

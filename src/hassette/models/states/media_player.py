from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class MediaPlayerStateValue(StrEnum):
    OFF = "off"
    ON = "on"
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STANDBY = "standby"
    BUFFERING = "buffering"


class MediaClass(StrEnum):
    ALBUM = "album"
    APP = "app"
    ARTIST = "artist"
    CHANNEL = "channel"
    COMPOSER = "composer"
    CONTRIBUTING_ARTIST = "contributing_artist"
    DIRECTORY = "directory"
    EPISODE = "episode"
    GAME = "game"
    GENRE = "genre"
    IMAGE = "image"
    MOVIE = "movie"
    MUSIC = "music"
    PLAYLIST = "playlist"
    PODCAST = "podcast"
    SEASON = "season"
    TRACK = "track"
    TV_SHOW = "tv_show"
    URL = "url"
    VIDEO = "video"


class MediaType(StrEnum):
    ALBUM = "album"
    APP = "app"
    APPS = "apps"
    ARTIST = "artist"
    CHANNEL = "channel"
    CHANNELS = "channels"
    COMPOSER = "composer"
    CONTRIBUTING_ARTIST = "contributing_artist"
    EPISODE = "episode"
    GAME = "game"
    GENRE = "genre"
    IMAGE = "image"
    MOVIE = "movie"
    MUSIC = "music"
    PLAYLIST = "playlist"
    PODCAST = "podcast"
    SEASON = "season"
    TRACK = "track"
    TVSHOW = "tvshow"
    URL = "url"
    VIDEO = "video"


class RepeatMode(StrEnum):
    ALL = "all"
    OFF = "off"
    ONE = "one"


class MediaPlayerEntityCapabilityAttribute(StrEnum):
    INPUT_SOURCE_LIST = "source_list"
    SOUND_MODE_LIST = "sound_mode_list"


class MediaPlayerEntityStateAttribute(StrEnum):
    MEDIA_VOLUME_LEVEL = "volume_level"
    MEDIA_VOLUME_MUTED = "is_volume_muted"
    MEDIA_CONTENT_ID = "media_content_id"
    MEDIA_CONTENT_TYPE = "media_content_type"
    MEDIA_DURATION = "media_duration"
    MEDIA_POSITION = "media_position"
    MEDIA_POSITION_UPDATED_AT = "media_position_updated_at"
    MEDIA_TITLE = "media_title"
    MEDIA_ARTIST = "media_artist"
    MEDIA_ALBUM_NAME = "media_album_name"
    MEDIA_ALBUM_ARTIST = "media_album_artist"
    MEDIA_TRACK = "media_track"
    MEDIA_SERIES_TITLE = "media_series_title"
    MEDIA_SEASON = "media_season"
    MEDIA_EPISODE = "media_episode"
    MEDIA_CHANNEL = "media_channel"
    MEDIA_PLAYLIST = "media_playlist"
    APP_ID = "app_id"
    APP_NAME = "app_name"
    INPUT_SOURCE = "source"
    SOUND_MODE = "sound_mode"
    MEDIA_SHUFFLE = "shuffle"
    MEDIA_REPEAT = "repeat"
    GROUP_MEMBERS = "group_members"
    ENTITY_PICTURE_LOCAL = "entity_picture_local"


class MediaPlayerEnqueue(StrEnum):
    ADD = "add"
    NEXT = "next"
    PLAY = "play"
    REPLACE = "replace"


class MediaPlayerDeviceClass(StrEnum):
    TV = "tv"
    SPEAKER = "speaker"
    RECEIVER = "receiver"
    PROJECTOR = "projector"


class MediaPlayerEntityFeature(IntFlag):
    PAUSE = 1
    SEEK = 2
    VOLUME_SET = 4
    VOLUME_MUTE = 8
    PREVIOUS_TRACK = 16
    NEXT_TRACK = 32
    TURN_ON = 128
    TURN_OFF = 256
    PLAY_MEDIA = 512
    VOLUME_STEP = 1024
    SELECT_SOURCE = 2048
    STOP = 4096
    CLEAR_PLAYLIST = 8192
    PLAY = 16384
    SHUFFLE_SET = 32768
    SELECT_SOUND_MODE = 65536
    BROWSE_MEDIA = 131072
    REPEAT_SET = 262144
    GROUPING = 524288
    MEDIA_ANNOUNCE = 1048576
    MEDIA_ENQUEUE = 2097152
    SEARCH_MEDIA = 4194304


class MediaPlayerAttributes(AttributesBase):
    app_id: str | None = Field(default=None)
    app_name: str | None = Field(default=None)
    device_class: MediaPlayerDeviceClass | None = Field(default=None)
    group_members: list[str] | None = Field(default=None)
    is_volume_muted: bool | None = Field(default=None)
    media_album_artist: str | None = Field(default=None)
    media_album_name: str | None = Field(default=None)
    media_artist: str | None = Field(default=None)
    media_channel: str | None = Field(default=None)
    media_content_id: str | None = Field(default=None)
    media_content_type: MediaType | str | None = Field(default=None)
    media_duration: int | None = Field(default=None)
    media_episode: str | None = Field(default=None)
    media_image_hash: str | None = Field(default=None)
    media_image_remotely_accessible: bool | None = Field(default=None)
    media_image_url: str | None = Field(default=None)
    media_playlist: str | None = Field(default=None)
    media_position_updated_at: ZonedDateTime | None = Field(default=None)
    media_position: int | None = Field(default=None)
    media_season: str | None = Field(default=None)
    media_series_title: str | None = Field(default=None)
    media_title: str | None = Field(default=None)
    media_track: int | None = Field(default=None)
    repeat: RepeatMode | str | None = Field(default=None)
    shuffle: bool | None = Field(default=None)
    sound_mode_list: list[str] | None = Field(default=None)
    sound_mode: str | None = Field(default=None)
    source_list: list[str] | None = Field(default=None)
    source: str | None = Field(default=None)
    state: MediaPlayerStateValue | None = Field(default=None)
    volume_level: float | None = Field(default=None)
    volume_step: float | None = Field(default=None)

    @field_validator("media_position_updated_at", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: str | ZonedDateTime | None) -> ZonedDateTime | None:
        return convert_datetime_str_to_system_tz(value)

    @property
    def supports_pause(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.PAUSE)

    @property
    def supports_seek(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.SEEK)

    @property
    def supports_volume_set(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.VOLUME_SET)

    @property
    def supports_volume_mute(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.VOLUME_MUTE)

    @property
    def supports_previous_track(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.PREVIOUS_TRACK)

    @property
    def supports_next_track(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.NEXT_TRACK)

    @property
    def supports_turn_on(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.TURN_ON)

    @property
    def supports_turn_off(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.TURN_OFF)

    @property
    def supports_play_media(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.PLAY_MEDIA)

    @property
    def supports_volume_step(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.VOLUME_STEP)

    @property
    def supports_select_source(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.SELECT_SOURCE)

    @property
    def supports_stop(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.STOP)

    @property
    def supports_clear_playlist(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.CLEAR_PLAYLIST)

    @property
    def supports_play(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.PLAY)

    @property
    def supports_shuffle_set(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.SHUFFLE_SET)

    @property
    def supports_select_sound_mode(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.SELECT_SOUND_MODE)

    @property
    def supports_browse_media(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.BROWSE_MEDIA)

    @property
    def supports_repeat_set(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.REPEAT_SET)

    @property
    def supports_grouping(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.GROUPING)

    @property
    def supports_media_announce(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.MEDIA_ANNOUNCE)

    @property
    def supports_media_enqueue(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.MEDIA_ENQUEUE)

    @property
    def supports_search_media(self) -> bool:
        return self.has_feature(MediaPlayerEntityFeature.SEARCH_MEDIA)


class MediaPlayerState(StringBaseState):
    """Representation of a Home Assistant media_player state.

    See: https://www.home-assistant.io/integrations/media_player/
    """

    domain: Literal["media_player"]

    attributes: MediaPlayerAttributes

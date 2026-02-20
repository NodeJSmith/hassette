"""IntFlag enums for Home Assistant entity supported_features bitmasks.

Each enum mirrors the corresponding ``EntityFeature`` IntFlag in HA core so
that users can check entity capabilities with typed helpers instead of raw
bitwise operations.

Only the six domains called out in issue #272 are covered here.  Additional
domains (alarm_control_panel, camera, siren, humidifier, water_heater,
remote, update, weather, calendar, lock, valve, …) can be added later.
"""

from enum import IntFlag


class LockEntityFeature(IntFlag):
    """Supported features of the lock entity.

    See: https://www.home-assistant.io/integrations/lock/
    """

    OPEN = 1


class LightEntityFeature(IntFlag):
    """Supported features of the light entity.

    See: https://www.home-assistant.io/integrations/light/
    """

    EFFECT = 4
    FLASH = 8
    TRANSITION = 32


class ClimateEntityFeature(IntFlag):
    """Supported features of the climate entity.

    See: https://www.home-assistant.io/integrations/climate/
    """

    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    TARGET_HUMIDITY = 4
    FAN_MODE = 8
    PRESET_MODE = 16
    SWING_MODE = 32
    TURN_OFF = 128
    TURN_ON = 256
    SWING_HORIZONTAL_MODE = 512


class CoverEntityFeature(IntFlag):
    """Supported features of the cover entity.

    See: https://www.home-assistant.io/integrations/cover/
    """

    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
    OPEN_TILT = 16
    CLOSE_TILT = 32
    STOP_TILT = 64
    SET_TILT_POSITION = 128


class FanEntityFeature(IntFlag):
    """Supported features of the fan entity.

    See: https://www.home-assistant.io/integrations/fan/
    """

    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8
    TURN_OFF = 16
    TURN_ON = 32


class MediaPlayerEntityFeature(IntFlag):
    """Supported features of the media_player entity.

    See: https://www.home-assistant.io/integrations/media_player/
    """

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


class VacuumEntityFeature(IntFlag):
    """Supported features of the vacuum entity.

    Deprecated flags (TURN_ON, TURN_OFF, BATTERY, STATUS, MAP, STATE) are
    omitted — they are not supported by ``StateVacuumEntity``.

    See: https://www.home-assistant.io/integrations/vacuum/
    """

    PAUSE = 4
    STOP = 8
    RETURN_HOME = 16
    FAN_SPEED = 32
    SEND_COMMAND = 256
    LOCATE = 512
    CLEAN_SPOT = 1024
    START = 8192
    CLEAN_AREA = 16384

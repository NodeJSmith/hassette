import typing

from hassette.models.states import (
    AiTaskState,
    AssistSatelliteState,
    AutomationState,
    BinarySensor_BaseState,
    ButtonState,
    CalendarState,
    CameraState,
    ClimateState,
    ConversationState,
    CoverState,
    DeviceTrackerState,
    EventState,
    FanState,
    HumidifierState,
    InputDatetimeState,
    LockState,
    MediaPlayerState,
    NumberState,
    PersonState,
    RemoteState,
    SceneState,
    ScriptState,
    Sensor_BaseState,
    SttState,
    SunState,
    SwitchState,
    TimerState,
    TtsState,
    UpdateState,
    WeatherState,
    ZoneState,
)

from .base import BaseEntity
from .light import LightEntity

EntityT = typing.TypeVar("EntityT")

# TODO:
# actually implement these entities
# this will likely take a while, but we want placeholders in the meantime


class AutomationEntity(BaseEntity[AutomationState]):
    pass


class ButtonEntity(BaseEntity[ButtonState]):
    pass


class CameraEntity(BaseEntity[CameraState]):
    pass


class AssistSatelliteEntity(BaseEntity[AssistSatelliteState]):
    pass


class AiTaskEntity(BaseEntity[AiTaskState]):
    pass


class LockEntity(BaseEntity[LockState]):
    pass


class InputDateTimeEntity(BaseEntity[InputDatetimeState]):
    pass


class CalendarEntity(BaseEntity[CalendarState]):
    pass


class ClimateEntity(BaseEntity[ClimateState]):
    pass


class ConversationEntity(BaseEntity[ConversationState]):
    pass


class CoverEntity(BaseEntity[CoverState]):
    pass


class DeviceTrackerEntity(BaseEntity[DeviceTrackerState]):
    pass


class EventEntity(BaseEntity[EventState]):
    pass


class FanEntity(BaseEntity[FanState]):
    pass


class HumidifierEntity(BaseEntity[HumidifierState]):
    pass


class MediaPlayerEntity(BaseEntity[MediaPlayerState]):
    pass


class NumberEntity(BaseEntity[NumberState]):
    pass


class PersonEntity(BaseEntity[PersonState]):
    pass


class RemoteEntity(BaseEntity[RemoteState]):
    pass


class SceneEntity(BaseEntity[SceneState]):
    pass


class ScriptEntity(BaseEntity[ScriptState]):
    pass


class SttEntity(BaseEntity[SttState]):
    pass


class SunEntity(BaseEntity[SunState]):
    pass


class SwitchEntity(BaseEntity[SwitchState]):
    pass


class TimerEntity(BaseEntity[TimerState]):
    pass


class TtsEntity(BaseEntity[TtsState]):
    pass


class UpdateEntity(BaseEntity[UpdateState]):
    pass


class WeatherEntity(BaseEntity[WeatherState]):
    pass


class ZoneEntity(BaseEntity[ZoneState]):
    pass


class SensorEntity(BaseEntity[Sensor_BaseState]):
    pass


class BinarySensorEntity(BaseEntity[BinarySensor_BaseState]):
    pass


__all__ = [
    "AiTaskEntity",
    "AssistSatelliteEntity",
    "AutomationEntity",
    "BaseEntity",
    "BinarySensorEntity",
    "ButtonEntity",
    "CalendarEntity",
    "CameraEntity",
    "ClimateEntity",
    "ConversationEntity",
    "CoverEntity",
    "DeviceTrackerEntity",
    "EntityT",
    "EventEntity",
    "FanEntity",
    "HumidifierEntity",
    "LightEntity",
    "LockEntity",
    "MediaPlayerEntity",
    "NumberEntity",
    "PersonEntity",
    "RemoteEntity",
    "SceneEntity",
    "ScriptEntity",
    "SensorEntity",
    "SttEntity",
    "SunEntity",
    "SwitchEntity",
    "TimerEntity",
    "TtsEntity",
    "UpdateEntity",
    "WeatherEntity",
    "ZoneEntity",
]

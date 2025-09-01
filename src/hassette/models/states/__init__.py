import typing
from contextlib import suppress
from logging import getLogger
from warnings import warn

from pydantic import BaseModel, ConfigDict

from .ai_task import AiTaskState
from .assist_satellite import AssistSatelliteState
from .automation import AutomationState
from .base import BaseState, StateT, StateValueT
from .binary_sensors import (
    BinarySensor_BaseState,
    BinarySensor_BatteryChargingState,
    BinarySensor_ConnectivityState,
    BinarySensor_DoorState,
    BinarySensor_LightState,
    BinarySensor_MotionState,
    BinarySensor_PlugState,
    BinarySensor_PowerState,
    BinarySensor_ProblemState,
    BinarySensor_UnknownState,
)
from .button import ButtonState
from .calendar import CalendarState
from .camera import CameraState
from .climate import ClimateState
from .conversation import ConversationState
from .cover import CoverState
from .device_tracker import DeviceTrackerState
from .event import EventState
from .fan import FanState
from .humidifier import HumidifierState
from .input_boolean import InputBooleanState
from .input_button import InputButtonState
from .input_datetime import InputDatetimeState
from .input_number import InputNumberState
from .input_text import InputTextState
from .light import LightState
from .lock import LockState
from .media_player import MediaPlayerState
from .number import NumberState
from .person import PersonState
from .remote import RemoteState
from .scene import SceneState
from .script import ScriptState
from .select import SelectState
from .sensors import (
    Sensor_BaseState,
    Sensor_BatteryState,
    Sensor_DistanceState,
    Sensor_DurationState,
    Sensor_EnergyState,
    Sensor_EnumState,
    Sensor_FallbackState,
    Sensor_HumidityState,
    Sensor_IlluminanceState,
    Sensor_MonetaryState,
    Sensor_Pm25State,
    Sensor_PrecipitationIntensityState,
    Sensor_PressureState,
    Sensor_SignalStrengthState,
    Sensor_TemperatureState,
    Sensor_TimestampState,
    Sensor_WindDirectionState,
    Sensor_WindSpeedState,
)
from .stt import SttState
from .sun import SunState
from .switch import SwitchState
from .timer import TimerState
from .todo import TodoState
from .tts import TtsState
from .update import UpdateState
from .weather import WeatherState
from .zone import ZoneState

if typing.TYPE_CHECKING:
    from hassette.models.events import HassStateDict

HelperUnion = (
    InputBooleanState | InputDatetimeState | InputNumberState | InputTextState | SelectState | InputButtonState
)

SensorUnion = (
    Sensor_BatteryState
    | Sensor_DistanceState
    | Sensor_DurationState
    | Sensor_EnergyState
    | Sensor_EnumState
    | Sensor_HumidityState
    | Sensor_IlluminanceState
    | Sensor_MonetaryState
    | Sensor_Pm25State
    | Sensor_PrecipitationIntensityState
    | Sensor_PressureState
    | Sensor_SignalStrengthState
    | Sensor_TemperatureState
    | Sensor_TimestampState
    | Sensor_WindDirectionState
    | Sensor_WindSpeedState
    | Sensor_BaseState
    | Sensor_FallbackState
)
BinarySensorUnion = (
    BinarySensor_BatteryChargingState
    | BinarySensor_ConnectivityState
    | BinarySensor_DoorState
    | BinarySensor_LightState
    | BinarySensor_MotionState
    | BinarySensor_PlugState
    | BinarySensor_PowerState
    | BinarySensor_ProblemState
    | BinarySensor_UnknownState
    | BinarySensor_BaseState
)
BaseSensorState = SensorUnion | BinarySensorUnion

StateUnion = (
    AiTaskState
    | AssistSatelliteState
    | AutomationState
    | ButtonState
    | CalendarState
    | CameraState
    | ClimateState
    | ConversationState
    | CoverState
    | DeviceTrackerState
    | EventState
    | FanState
    | HumidifierState
    | LightState
    | LockState
    | MediaPlayerState
    | NumberState
    | PersonState
    | RemoteState
    | SceneState
    | ScriptState
    | SttState
    | SunState
    | SwitchState
    | TimerState
    | TodoState
    | TtsState
    | UpdateState
    | WeatherState
    | ZoneState
    | HelperUnion
    | SensorUnion
    | BinarySensorUnion
    | BaseState
)


LOGGER = getLogger(__name__)


@typing.overload
def try_convert_state(data: None) -> None: ...


@typing.overload
def try_convert_state(data: "HassStateDict") -> StateUnion: ...


def try_convert_state(data: "HassStateDict | None") -> StateUnion | None:
    """
    Attempts to convert a dictionary representation of a state into a specific state type.
    If the conversion fails, it returns an UnknownState.
    """

    class _AnyState(BaseModel):
        model_config = ConfigDict(coerce_numbers_to_str=True, arbitrary_types_allowed=True)
        state: StateUnion

    class _AnySensor(BaseModel):
        model_config = ConfigDict(coerce_numbers_to_str=True, arbitrary_types_allowed=True)
        state: SensorUnion

    class _AnyBinarySensor(BaseModel):
        model_config = ConfigDict(coerce_numbers_to_str=True, arbitrary_types_allowed=True)
        state: BinarySensorUnion

    if data is None:
        return None

    if "event" in data:
        LOGGER.error("Data contains 'event' key, expected state data, not event data", stacklevel=2)
        return None

    # ensure it's wrapped in a dict with "state" key
    if "entity_id" in data:
        convert_envelope = {"state": data}
    else:
        convert_envelope = data
        LOGGER.debug("Data does not contain 'entity_id', assuming it is a state dict: %s", data, stacklevel=2)

    domain = None
    with suppress(Exception):
        domain = convert_envelope["state"]["entity_id"].split(".")[0]

    try:
        if domain and domain == "binary_sensor":
            result = _AnyBinarySensor.model_validate(convert_envelope).state
        elif domain and domain == "sensor":
            result = _AnySensor.model_validate(convert_envelope).state
        else:
            result = _AnyState.model_validate(convert_envelope).state
    except Exception:
        LOGGER.exception("Unable to convert state data %s", data)
        return None

    if type(result) is BaseState:
        warn(f"try_convert_state result {result.entity_id} is of type BaseState", stacklevel=2)

    return result


__all__ = [
    "AutomationState",
    "BinarySensor_BaseState",
    "BinarySensor_BatteryChargingState",
    "BinarySensor_ConnectivityState",
    "BinarySensor_DoorState",
    "BinarySensor_LightState",
    "BinarySensor_MotionState",
    "BinarySensor_PlugState",
    "BinarySensor_PowerState",
    "BinarySensor_ProblemState",
    "BinarySensor_UnknownState",
    "ButtonState",
    "CalendarState",
    "ClimateState",
    "ConversationState",
    "CoverState",
    "DeviceTrackerState",
    "EventState",
    "FanState",
    "HumidifierState",
    "InputBooleanState",
    "InputButtonState",
    "InputDatetimeState",
    "InputNumberState",
    "InputTextState",
    "LightState",
    "MediaPlayerState",
    "NumberState",
    "PersonState",
    "RemoteState",
    "SceneState",
    "ScriptState",
    "SelectState",
    "Sensor_BaseState",
    "Sensor_BatteryState",
    "Sensor_DistanceState",
    "Sensor_DurationState",
    "Sensor_EnergyState",
    "Sensor_EnumState",
    "Sensor_HumidityState",
    "Sensor_IlluminanceState",
    "Sensor_MonetaryState",
    "Sensor_Pm25State",
    "Sensor_PrecipitationIntensityState",
    "Sensor_PressureState",
    "Sensor_SignalStrengthState",
    "Sensor_TemperatureState",
    "Sensor_TimestampState",
    "Sensor_WindDirectionState",
    "Sensor_WindSpeedState",
    "StateT",
    "StateUnion",
    "StateValueT",
    "SttState",
    "SunState",
    "SwitchState",
    "TimerState",
    "TtsState",
    "UpdateState",
    "WeatherState",
    "ZoneState",
    "try_convert_state",
]

import typing
from logging import getLogger
from warnings import warn

from pydantic import BaseModel, ConfigDict, Field

from .air_quality import AirQualityState
from .alarm_control_panel import AlarmControlPanelState
from .assist_satellite import AssistSatelliteState
from .automation import AutomationState
from .base import BaseState, StateT, StateValueT
from .calendar import CalendarState
from .camera import CameraState
from .climate import ClimateState
from .device_tracker import DeviceTrackerState
from .event import EventState
from .fan import FanState
from .humidifier import HumidifierState
from .image_processing import ImageProcessingState
from .input import (
    InputBooleanState,
    InputButtonState,
    InputDatetimeState,
    InputNumberState,
    InputSelectState,
    InputTextState,
)
from .light import LightState
from .media_player import MediaPlayerState
from .number import NumberState
from .person import PersonState
from .remote import RemoteState
from .scene import SceneState
from .script import ScriptState
from .select import SelectState
from .sensor import SensorAttributes, SensorState
from .simple import (
    AiTaskState,
    BinarySensorState,
    ButtonState,
    ConversationState,
    CoverState,
    DateState,
    DateTimeState,
    LockState,
    NotifyState,
    SttState,
    SwitchState,
    TimeState,
    TodoState,
    TtsState,
    ValveState,
)
from .siren import SirenState
from .sun import SunState
from .text import TextState
from .timer import TimerState
from .update import UpdateState
from .vacuum import VacuumState
from .water_heater import WaterHeaterState
from .weather import WeatherState
from .zone import ZoneState

if typing.TYPE_CHECKING:
    from hassette.core.events import HassStateDict

# _StateUnion does not include BaseState, which is the fallback type if no specific type matches.
_StateUnion: typing.TypeAlias = (
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
    | WaterHeaterState
    | DateState
    | DateTimeState
    | TimeState
    | TextState
    | VacuumState
    | SirenState
    | NotifyState
    | VacuumState
    | ValveState
    | ImageProcessingState
    | AirQualityState
    | AlarmControlPanelState
    | InputBooleanState
    | InputDatetimeState
    | InputNumberState
    | InputTextState
    | SelectState
    | InputButtonState
    | InputSelectState
    | SensorState
    | BinarySensorState
)

StateUnion = _StateUnion | BaseState
"""A union of all specific state types and BaseState. Used for type hinting when the specific type is not known."""

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
        state: _StateUnion = Field(discriminator="domain")

    if data is None:
        return None

    if "event" in data:
        LOGGER.error("Data contains 'event' key, expected state data, not event data", stacklevel=2)
        return None

    try:
        data["domain"] = data["entity_id"].split(".")[0]
        return _AnyState.model_validate({"state": data}).state
    except Exception:
        LOGGER.exception("Unable to convert state data %s", data)

    try:
        result = BaseState.model_validate(data)
        warn(f"try_convert_state result {result.entity_id} is of type BaseState", stacklevel=2)
        return result
    except Exception:
        LOGGER.exception("Unable to convert state data to BaseState %s", data)
        return None


__all__ = [
    "AutomationState",
    "BaseState",
    "BinarySensorState",
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
    "InputSelectState",
    "InputTextState",
    "LightState",
    "MediaPlayerState",
    "NumberState",
    "PersonState",
    "RemoteState",
    "SceneState",
    "ScriptState",
    "SelectState",
    "SensorAttributes",
    "SensorState",
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

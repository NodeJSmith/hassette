import typing
from contextlib import suppress
from logging import getLogger
from warnings import warn

from pydantic import BaseModel, ConfigDict

from .air_quality import AirQualityState
from .alarm_control_panel import AlarmControlPanelState
from .assist_satellite import AssistSatelliteState
from .automation import AutomationState
from .base import DOMAIN_MAP, BaseState, StateT, StateValueT
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
    from hassette.models.events import HassStateDict


StateUnion: typing.TypeAlias = (
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

    if data is None:
        return None

    if "event" in data:
        LOGGER.error("Data contains 'event' key, expected state data, not event data", stacklevel=2)
        return None

    # ensure it's wrapped in a dict with "state" key
    convert_envelope = {"state": data}

    domain = None
    cls: type[BaseState] | None = None

    with suppress(Exception):
        domain = data["entity_id"].split(".")[0]

    if domain:
        match domain:
            case "binary_sensor":
                cls = BinarySensorState
            case "sensor":
                cls = SensorState
            case _:
                cls = DOMAIN_MAP.get(domain)

    if cls is not None:
        try:
            return cls.model_validate(data)
        except Exception:
            LOGGER.exception("Failed to convert state for domain %s", domain)

    try:
        result = _AnyState.model_validate(convert_envelope).state
    except Exception:
        LOGGER.exception("Unable to convert state data %s", data)
        return None

    if type(result) is BaseState:
        warn(f"try_convert_state result {result.entity_id} is of type BaseState", stacklevel=2)

    return result


__all__ = [
    "AutomationState",
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

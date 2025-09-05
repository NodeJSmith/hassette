from typing import Literal

from .base import BoolBaseState, DateTimeBaseState, InstantBaseState, NumericBaseState, StringBaseState, TimeBaseState


class AiTaskState(StringBaseState):
    domain: Literal["ai_task"]


class ButtonState(StringBaseState):
    domain: Literal["button"]


class ConversationState(StringBaseState):
    domain: Literal["conversation"]


class CoverState(StringBaseState):
    domain: Literal["cover"]


class DateState(DateTimeBaseState):
    domain: Literal["date"]


class DateTimeState(DateTimeBaseState):
    domain: Literal["datetime"]


class LockState(StringBaseState):
    domain: Literal["lock"]


class NotifyState(StringBaseState):
    domain: Literal["notify"]


class SttState(StringBaseState):
    domain: Literal["stt"]


class SwitchState(StringBaseState):
    domain: Literal["switch"]


class TimeState(TimeBaseState):
    domain: Literal["time"]


class TodoState(NumericBaseState):
    domain: Literal["todo"]


class TtsState(InstantBaseState):
    domain: Literal["tts"]


class ValveState(StringBaseState):
    domain: Literal["valve"]


class BinarySensorState(BoolBaseState):
    domain: Literal["binary_sensor"]

from typing import Literal

from .base import BoolBaseState, DateTimeBaseState, NumericBaseState, StringBaseState, TimeBaseState


class AiTaskState(StringBaseState):
    """Representation of a Home Assistant ai_task state.

    See: https://www.home-assistant.io/integrations/ai_task/
    """

    domain: Literal["ai_task"]


class ButtonState(StringBaseState):
    """Representation of a Home Assistant button state.

    See: https://www.home-assistant.io/integrations/button/
    """

    domain: Literal["button"]


class ConversationState(StringBaseState):
    """Representation of a Home Assistant conversation state.

    See: https://www.home-assistant.io/integrations/conversation/
    """

    domain: Literal["conversation"]


class CoverState(StringBaseState):
    """Representation of a Home Assistant cover state.

    See: https://www.home-assistant.io/integrations/cover/
    """

    domain: Literal["cover"]


class DateState(DateTimeBaseState):
    """Representation of a Home Assistant date state.

    See: https://www.home-assistant.io/integrations/date/
    """

    domain: Literal["date"]


class DateTimeState(DateTimeBaseState):
    """Representation of a Home Assistant datetime state.

    See: https://www.home-assistant.io/integrations/datetime/
    """

    domain: Literal["datetime"]


class LockState(StringBaseState):
    """Representation of a Home Assistant lock state.

    See: https://www.home-assistant.io/integrations/lock/
    """

    domain: Literal["lock"]


class NotifyState(StringBaseState):
    """Representation of a Home Assistant notify state.

    See: https://www.home-assistant.io/integrations/notify/
    """

    domain: Literal["notify"]


class SttState(StringBaseState):
    """Representation of a Home Assistant stt state.

    See: https://www.home-assistant.io/integrations/stt/
    """

    domain: Literal["stt"]


class SwitchState(StringBaseState):
    """Representation of a Home Assistant switch state.

    See: https://www.home-assistant.io/integrations/switch/
    """

    domain: Literal["switch"]


class TimeState(TimeBaseState):
    """Representation of a Home Assistant time state.

    See: https://www.home-assistant.io/integrations/time/
    """

    domain: Literal["time"]


class TodoState(NumericBaseState):
    """Representation of a Home Assistant todo state.

    See: https://www.home-assistant.io/integrations/todo/
    """

    domain: Literal["todo"]


class TtsState(DateTimeBaseState):
    """Representation of a Home Assistant tts state.

    See: https://www.home-assistant.io/integrations/tts/
    """

    domain: Literal["tts"]


class ValveState(StringBaseState):
    """Representation of a Home Assistant valve state.

    See: https://www.home-assistant.io/integrations/valve/
    """

    domain: Literal["valve"]


class BinarySensorState(BoolBaseState):
    """Representation of a Home Assistant binary_sensor state.

    See: https://www.home-assistant.io/integrations/binary_sensor/
    """

    domain: Literal["binary_sensor"]

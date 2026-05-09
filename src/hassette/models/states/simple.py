from typing import Literal

from .base import BoolBaseState, DateTimeBaseState, NumericBaseState, TimeBaseState


class AiTaskState(DateTimeBaseState):
    """Representation of a Home Assistant ai_task state.

    See: https://www.home-assistant.io/integrations/ai_task/
    """

    domain: Literal["ai_task"]


class ButtonState(DateTimeBaseState):
    """Representation of a Home Assistant button state.

    See: https://www.home-assistant.io/integrations/button/
    """

    domain: Literal["button"]


class ConversationState(DateTimeBaseState):
    """Representation of a Home Assistant conversation state.

    See: https://www.home-assistant.io/integrations/conversation/
    """

    domain: Literal["conversation"]


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


class NotifyState(DateTimeBaseState):
    """Representation of a Home Assistant notify state.

    See: https://www.home-assistant.io/integrations/notify/
    """

    domain: Literal["notify"]


class SttState(DateTimeBaseState):
    """Representation of a Home Assistant stt state.

    See: https://www.home-assistant.io/integrations/stt/
    """

    domain: Literal["stt"]


class SwitchState(BoolBaseState):
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


class BinarySensorState(BoolBaseState):
    """Representation of a Home Assistant binary_sensor state.

    See: https://www.home-assistant.io/integrations/binary_sensor/
    """

    domain: Literal["binary_sensor"]

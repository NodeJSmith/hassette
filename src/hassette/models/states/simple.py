from typing import Literal

from .base import DateTimeBaseState


class AiTaskState(DateTimeBaseState):
    """Representation of a Home Assistant ai_task state.

    See: https://www.home-assistant.io/integrations/ai_task/
    """

    domain: Literal["ai_task"]


class ConversationState(DateTimeBaseState):
    """Representation of a Home Assistant conversation state.

    See: https://www.home-assistant.io/integrations/conversation/
    """

    domain: Literal["conversation"]


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


class TtsState(DateTimeBaseState):
    """Representation of a Home Assistant tts state.

    See: https://www.home-assistant.io/integrations/tts/
    """

    domain: Literal["tts"]

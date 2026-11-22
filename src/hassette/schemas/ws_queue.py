"""Items carried on a ``/ws`` client queue, shared by RuntimeQueryService (producer) and the WS route (consumer)."""

from enum import Enum
from typing import Any


class WsClientSignal(Enum):
    """A control item on a WS client queue, telling the client's send loop to stop."""

    SHUTDOWN = "shutdown"
    """The service is shutting down."""

    TOO_SLOW = "too_slow"
    """The client fell a full queue behind and must reconnect to resync."""


WsQueueItem = dict[str, Any] | WsClientSignal
"""What a WS client queue carries: a pre-serialized broadcast message, or a signal to stop."""

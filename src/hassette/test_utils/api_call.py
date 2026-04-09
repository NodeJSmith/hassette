"""ApiCall — record of a single API method invocation.

Extracted from recording_api.py to break the circular import that would otherwise
exist between recording_api.py and sync_facade.py. Both modules import from here.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiCall:
    """Record of a single API method invocation.

    Write methods (``call_service``, ``set_state``, ``fire_event``) record their
    positional arguments in both ``args`` and ``kwargs`` so that
    :meth:`RecordingApi.assert_called` can use kwargs-only matching uniformly::

        recorder.assert_called("turn_on", entity_id="light.kitchen")

    ``args`` is available for direct positional inspection when needed, but
    ``assert_called`` does not check it — use ``kwargs`` for assertions.

    Attributes:
        method: Name of the method that was called (e.g. "turn_on").
        args: Positional arguments passed to the method (for inspection only).
        kwargs: Keyword arguments — the primary assertion surface. Write methods
            include positional args here as well for uniform kwargs-based matching.
    """

    method: str
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)

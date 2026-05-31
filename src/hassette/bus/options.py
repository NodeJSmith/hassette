"""Shared listener option types for the event bus.

``Options`` lives in its own module so both ``bus.py`` and the generated
``sync.py`` facade can import it without a circular import. ``bus.py`` imports
``BusSyncFacade`` from ``sync.py``, and the facade's wrapped signatures
reference ``Unpack[Options]`` at runtime — keeping ``Options`` here breaks the
cycle.
"""

from typing_extensions import TypedDict


class Options(TypedDict, total=False):
    once: bool
    """Whether the listener should be removed after one invocation."""

    debounce: float | None
    """Length of time in seconds to wait before invoking the handler, resetting if another event is received."""

    throttle: float | None
    """Length of time in seconds to wait before allowing the handler to be invoked again."""

    timeout: float | None
    """Per-listener timeout in seconds. Overrides the global event_handler_timeout_seconds config.
    None means fall through to the config default."""

    timeout_disabled: bool
    """When True, disables timeout enforcement for this listener regardless of config."""

"""Shared listener option types for the event bus.

``Options`` lives in its own module so both ``bus.py`` and the generated
``sync.py`` facade can import it without a circular import. ``bus.py`` imports
``BusSyncFacade`` from ``sync.py``, and the facade's wrapped signatures
reference ``Unpack[Options]`` at runtime — keeping ``Options`` here breaks the
cycle.
"""

from typing import Literal

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

    if_exists: Literal["error", "skip", "replace"]
    """Behavior when a listener with the same natural key ``(app_key, instance_index, name, topic)`` already exists.

    ``"error"`` (default) raises ``DuplicateListenerError``.
    ``"skip"`` returns the existing listener's subscription when the configuration matches;
    raises ``ValueError`` listing changed fields if the configuration differs.
    ``"replace"`` cancels the existing listener (recording ``cancelled_at`` in telemetry)
    and registers the new listener on the same natural-key row.

    The bus resolves ``if_exists`` per ``(name, topic)`` — the same name on a different
    topic is a different listener and does not collide.
    """

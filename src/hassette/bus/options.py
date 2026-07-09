"""Shared listener option types for the event bus.

``Options`` lives in its own module so both ``bus.py`` and the generated
``sync.py`` facade can import it without a circular import. ``bus.py`` imports
``BusSyncFacade`` from ``sync.py``, and the facade's wrapped signatures
reference ``Unpack[Options]`` at runtime — keeping ``Options`` here breaks the
cycle.
"""

from typing_extensions import TypedDict

from hassette.types.enums import BackpressurePolicy, ExecutionMode
from hassette.types.types import IfExistsPolicy


class Options(TypedDict, total=False):
    once: bool
    """Whether the listener should be removed after one invocation."""

    mode: ExecutionMode | str
    """Overlap behavior when a trigger fires while a prior invocation still runs.

    ``"single"`` drops the re-fire (the app-tier default), ``"restart"`` cancels the running
    invocation and starts a new one, ``"queued"`` serializes triggers in arrival order (bounded),
    ``"parallel"`` runs concurrently (the framework-tier default). When omitted, the effective
    default is tier-aware: ``parallel`` for framework listeners, ``single`` for app listeners.
    """

    debounce: float | None
    """Length of time in seconds to wait before invoking the handler, resetting if another event is received."""

    throttle: float | None
    """Length of time in seconds to wait before allowing the handler to be invoked again."""

    timeout: float | None
    """Per-listener timeout in seconds. Overrides the global event_handler_timeout_seconds config.
    None means fall through to the config default."""

    timeout_disabled: bool
    """When True, disables timeout enforcement for this listener regardless of config."""

    backpressure: BackpressurePolicy | str
    """Saturation policy for this listener when the dispatch concurrency semaphore is at capacity.

    ``"block"`` (default) waits for a slot, preserving today's blocking behavior unchanged.
    ``"drop_newest"`` skips the event immediately when the bus is saturated — the handler is not
    invoked and one drop is recorded on the listener. When omitted, the effective default is
    ``"block"``, so existing listeners see no behavior change.
    """

    if_exists: IfExistsPolicy
    """Behavior when a listener with the same natural key ``(app_key, instance_index, name, topic)`` already exists.

    ``"error"`` (default) raises ``DuplicateListenerError``.
    ``"skip"`` returns the existing listener's subscription when the configuration matches;
    raises ``ValueError`` listing changed fields if the configuration differs. The returned
    subscription is the same live handle as the original registrant's — cancelling it removes
    the listener for all holders (there is no reference counting).
    ``"replace"`` cancels the existing listener (recording ``cancelled_at`` in telemetry)
    and registers the new listener on the same natural-key row.

    Lambda/closure predicates compare by identity, so re-registering under ``"skip"`` with a
    freshly built lambda reports drift and raises; use a named predicate function or ``"replace"``.

    The bus resolves ``if_exists`` per ``(name, topic)`` — the same name on a different
    topic is a different listener and does not collide.
    """

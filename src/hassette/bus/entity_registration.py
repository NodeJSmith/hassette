"""Registration-time checks for entity-scoped listeners (``on_state_change`` / ``on_attribute_change``)."""

import difflib
import logging
import typing

from hassette.utils.glob_utils import is_glob

if typing.TYPE_CHECKING:
    from hassette.core.state_proxy import StateProxy
    from hassette.resources.base import Resource


def reject_glob_only_options(entity_id: str, *, immediate: bool, duration: float | None) -> None:
    """Raise if ``immediate`` or ``duration`` is combined with a glob ``entity_id``.

    Raises:
        ValueError: If a glob pattern is used with ``immediate=True`` or a ``duration``.
    """
    if immediate and is_glob(entity_id):
        raise ValueError(
            f"'immediate=True' is not supported with glob patterns. entity_id={entity_id!r} contains glob characters."
        )
    if duration is not None and is_glob(entity_id):
        raise ValueError(
            f"'duration' is not supported with glob patterns. entity_id={entity_id!r} contains glob characters."
        )


def warn_if_unknown_entity(
    logger: logging.Logger,
    owner: "Resource | None",
    state_proxy: "StateProxy | None",
    entity_id: str,
    name: str,
) -> None:
    """Log one WARNING when an app listener watches a literal entity ID missing from the state cache.

    Never raises and never blocks registration. Stays silent for glob patterns, framework-tier
    owners, and an empty or not-yet-loaded cache, where absence is not evidence of a typo.
    """
    if owner is None or is_glob(entity_id) or owner.source_tier != "app":
        return
    if state_proxy is None or not state_proxy.has_cache_entries or entity_id in state_proxy.states:
        return

    # list() snapshots the keys atomically: sync-facade registrations run off the event loop.
    matches = difflib.get_close_matches(entity_id, list(state_proxy.states), n=1)
    suggestion = f" (did you mean {matches[0]!r}?)" if matches else ""
    logger.warning(
        "Listener %r in app %r watches %r, which matches no known entity%s",
        name,
        owner.app_key,
        entity_id,
        suggestion,
        # Not ``app_key``: LogContextFilter overwrites that record attribute from contextvars.
        extra={"app": owner.app_key, "listener": name, "entity_id": entity_id},
    )

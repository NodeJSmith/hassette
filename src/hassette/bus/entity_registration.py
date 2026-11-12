"""Registration-time helpers for entity-scoped listeners (``on_state_change`` / ``on_attribute_change``).

Option checks, the unknown-entity warning, and the predicate lists each registration filters on.
"""

import difflib
import logging
import typing
from functools import partial
from typing import Any

from hassette.const import NOT_PROVIDED, FalseySentinel
from hassette.event_handling import predicates as P
from hassette.utils.glob_utils import is_glob

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette.core.state_proxy import StateProxy
    from hassette.resources.base import Resource
    from hassette.types import ComparisonCondition, Predicate


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

    Called only after the listener is registered, so an un-awaited or rejected registration stays silent.

    Never raises and never blocks registration. Stays silent for glob patterns, framework-tier
    owners, and an empty or not-yet-loaded cache, where absence is not evidence of a typo.
    """
    if owner is None or is_glob(entity_id) or owner.source_tier != "app":
        return
    if state_proxy is None or not state_proxy.has_cache_entries or entity_id in state_proxy.states:
        return

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


def _build_preds(
    entity_id: str,
    *,
    changed: "bool | ComparisonCondition | FalseySentinel",
    changed_from: Any,
    changed_to: Any,
    make_did_change: "Callable[[], Predicate]",
    make_comparison: "Callable[..., Predicate]",
    make_from: "Callable[..., Predicate]",
    make_to: "Callable[..., Predicate]",
) -> "tuple[list[Predicate], list[Predicate], list[Predicate]]":
    """Build ``(scope, filters, hold_preds)`` for a state/attribute change subscription.

    ``scope`` selects the events the listener is about: the entity, plus the change filter when ``changed`` was
    omitted (``NOT_PROVIDED`` behaves as ``True``). A ``changed`` the caller passed, ``changed_from`` and
    ``changed_to`` go in ``filters``, so their rejections are near-misses.
    """
    scope: list[Predicate] = [P.EntityMatches(entity_id)]
    filters: list[Predicate] = []
    hold_preds: list[Predicate] = [P.EntityMatches(entity_id)]

    if changed is NOT_PROVIDED:
        scope.append(make_did_change())
    elif changed is True:
        filters.append(make_did_change())
    elif changed:
        filters.append(make_comparison(condition=changed))

    if changed_from is not NOT_PROVIDED:
        filters.append(make_from(condition=changed_from))

    if changed_to is not NOT_PROVIDED:
        changed_to_pred = make_to(condition=changed_to)
        filters.append(changed_to_pred)
        hold_preds.append(changed_to_pred)

    return scope, filters, hold_preds


def build_state_preds(
    entity_id: str,
    *,
    changed: "bool | ComparisonCondition | FalseySentinel",
    changed_from: Any,
    changed_to: Any,
) -> "tuple[list[Predicate], list[Predicate], list[Predicate]]":
    """Return ``(scope, filters, hold_preds)`` for a state-change listener; ``hold_preds`` re-check a duration hold."""
    return _build_preds(
        entity_id,
        changed=changed,
        changed_from=changed_from,
        changed_to=changed_to,
        make_did_change=P.StateDidChange,
        make_comparison=P.StateComparison,
        make_from=P.StateFrom,
        make_to=P.StateTo,
    )


def build_attr_preds(
    entity_id: str,
    attr: str,
    *,
    changed: "bool | ComparisonCondition | FalseySentinel",
    changed_from: Any,
    changed_to: Any,
) -> "tuple[list[Predicate], list[Predicate], list[Predicate]]":
    """Return ``(scope, filters, hold_preds)`` for an attribute-change listener; ``hold_preds`` re-check a hold."""
    return _build_preds(
        entity_id,
        changed=changed,
        changed_from=changed_from,
        changed_to=changed_to,
        make_did_change=partial(P.AttrDidChange, attr),
        make_comparison=partial(P.AttrComparison, attr),
        make_from=partial(P.AttrFrom, attr),
        make_to=partial(P.AttrTo, attr),
    )

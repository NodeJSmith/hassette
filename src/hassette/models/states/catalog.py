"""State-class catalog: domain → BaseState subclass mapping.

This leaf module owns the STATE_CATALOG dict, register_state_converter, resolve, and
StateKey. It imports nothing from hassette.conversion — it sits below the conversion
layer in the package DAG so that models/states can be imported without pulling in conversion.

BaseState.__init_subclass__ writes this catalog; StateRegistry (conversion layer) reads it.
"""

from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hassette.exceptions import DomainRequiredError

if TYPE_CHECKING:
    from hassette.models.states.base import BaseState

_STATE_CATALOG: dict["StateKey", type["BaseState"]] = {}


@dataclass(frozen=True)
class StateKey:
    domain: Hashable | None = None
    """The domain of the entity (e.g., 'light', 'sensor')."""


def register_state_converter(state_class: type["BaseState"], domain: Hashable) -> None:
    """Register a state class for a specific domain.

    Args:
        state_class: The state class to register. Must be a subclass of BaseState.
        domain: The Home Assistant domain (e.g., "light", "sensor"). Must not be ``None`` —
            a ``None`` domain would be silently resolvable via ``resolve(domain=None)``.

    Raises:
        DomainRequiredError: If ``domain`` is ``None``.
    """
    if domain is None:
        raise DomainRequiredError(state_class)

    key = StateKey(domain=domain)
    _STATE_CATALOG[key] = state_class


def resolve(*, domain: Hashable | None = None) -> type["BaseState"] | None:
    """Resolve a state class from the catalog based on domain.

    Args:
        domain: The Home Assistant domain (e.g., "light", "sensor").

    Returns:
        The registered state class, or None if no match is found.
    """
    return _STATE_CATALOG.get(StateKey(domain=domain))


def snapshot_catalog() -> "dict[StateKey, type[BaseState]]":
    """Return a shallow copy of the current catalog state."""
    return dict(_STATE_CATALOG)


def restore_catalog(snap: "dict[StateKey, type[BaseState]]") -> None:
    """Replace the catalog contents with a previously captured snapshot."""
    # In-place clear+update (not a rebind), so every module-level importer of
    # _STATE_CATALOG keeps seeing the same live dict.
    _STATE_CATALOG.clear()
    _STATE_CATALOG.update(snap)

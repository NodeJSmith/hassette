"""Surface guard for the generated Bus sync facade.

The facade is generated into two modules — ``bus/sync.py`` holds the core registration
API, ``bus/sync_events.py`` holds the named-event shortcuts that ``BusSyncFacade``
inherits — so that neither file crosses the repo's file-size threshold. Callers only ever
see the merged surface via ``bus.sync``, and these tests pin it: every public ``Bus``
method has a facade counterpart, and the shortcuts really do arrive by inheritance.
"""

import inspect

from hassette_codegen.sync_facade import LIFECYCLE_METHODS

from hassette.bus.bus import Bus
from hassette.bus.sync import BusSyncFacade
from hassette.bus.sync_events import BusSyncEventShortcuts


def public_bus_methods() -> set[str]:
    """Every public method defined on Bus itself that the facade is expected to mirror."""
    return {
        name
        for name, obj in vars(Bus).items()
        if inspect.isfunction(obj) and not name.startswith("_") and name not in LIFECYCLE_METHODS
    }


def test_facade_mirrors_every_public_bus_method() -> None:
    """No Bus method is lost when the facade is split across two generated modules."""
    missing = sorted(name for name in public_bus_methods() if not hasattr(BusSyncFacade, name))
    assert not missing, f"BusSyncFacade is missing Bus methods: {missing}"


def test_named_event_shortcuts_are_inherited_not_duplicated() -> None:
    """The shortcuts live on the base class only — a copy in sync.py would drift silently."""
    assert "on_homeassistant_start" in vars(BusSyncEventShortcuts)
    assert "on_homeassistant_start" not in vars(BusSyncFacade)
    assert issubclass(BusSyncFacade, BusSyncEventShortcuts)

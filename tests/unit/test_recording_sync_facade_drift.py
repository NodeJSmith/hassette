"""CI-enforced drift detection between ApiSyncFacade and _RecordingSyncFacade.

If Api gains a new convenience method (turn_on variant, etc.), ApiSyncFacade
gets a sync wrapper automatically via the code generator. This test asserts
that _RecordingSyncFacade has a matching method so the recording contract
stays complete.
"""

import inspect

from hassette.api.sync import ApiSyncFacade
from hassette.test_utils.sync_facade import _RecordingSyncFacade

# Resource lifecycle hooks — these come from ApiSyncFacade's Resource base class,
# not from the real Api surface. They are not user-facing test API methods and
# must not be drift-compared. `_RecordingSyncFacade` is a plain class (not a
# Resource subclass) and intentionally does not implement them.
_RESOURCE_LIFECYCLE_METHODS = frozenset(
    {
        "on_initialize",
        "before_initialize",
        "after_initialize",
        "on_shutdown",
        "before_shutdown",
        "after_shutdown",
        "initialize",
        "shutdown",
        "restart",
        "cleanup",
    }
)


def _public_methods(cls: type) -> set[str]:
    """Return the set of public method names defined on cls (not inherited), excluding Resource lifecycle hooks."""
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_") and name in cls.__dict__ and name not in _RESOURCE_LIFECYCLE_METHODS
    }


def test_recording_sync_facade_covers_api_sync_facade() -> None:
    """_RecordingSyncFacade must define a method for every public method on ApiSyncFacade.

    When Api adds a new convenience method, generate_sync_facade.py produces a
    matching method in ApiSyncFacade. This test fails if _RecordingSyncFacade
    is not updated to match, catching the drift that would otherwise silently
    recreate the RecordingApi.sync=Mock() safety hole for new methods.
    """
    sync_facade_methods = _public_methods(ApiSyncFacade)
    recording_facade_methods = _public_methods(_RecordingSyncFacade)

    missing = sync_facade_methods - recording_facade_methods
    assert not missing, (
        f"_RecordingSyncFacade is missing sync methods present in ApiSyncFacade: {sorted(missing)}. "
        f"Add them to src/hassette/test_utils/sync_facade.py."
    )

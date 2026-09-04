"""Public test API for hassette apps.

``hassette.testing`` is the sole public test API namespace. Every symbol in
``__all__`` is stable and documented for end users writing tests for their
own Hassette automations.

Private (`_`-prefixed) modules in this package (``_harness``, ``_simulation``,
``_time_control``, ``_sync_facade``, ``_reset``, ``_server``, ``_ws_mocks``,
``_factories``) are implementation details that Tier 1 symbols transitively
depend on. They ship in the wheel because the public API needs them at
runtime, but they are not part of the supported surface and may change
without notice.

Internal framework test infrastructure (web-layer factories, seed scenario
helpers, codegen-only modules, etc.) lives in ``tests.support`` — outside
``src/`` and absent from the wheel.

``dummy_cache`` is resolved lazily via module ``__getattr__`` rather than an
eager top-level import: it's the only Tier 1 symbol backed by ``fixtures.py``,
which imports ``pytest`` (an optional ``[test]``-extra dependency) at module
level. An eager import would make every Tier 1 symbol -- not just
``dummy_cache`` -- require ``pytest`` to be installed, just because they
share this package's ``__init__.py``.
"""

from typing import TYPE_CHECKING

# Self-alias pattern (`X as X`) signals to ruff/pyright that these are intentional re-exports.
from ._factories import create_call_service_event as create_call_service_event
from ._factories import create_state_change_event as create_state_change_event
from ._factories import make_full_state_change_event as make_full_state_change_event
from ._factories import make_light_state_dict as make_light_state_dict
from ._factories import make_sensor_state_dict as make_sensor_state_dict
from ._factories import make_state_dict as make_state_dict
from ._factories import make_switch_state_dict as make_switch_state_dict
from ._factories import make_typed_state as make_typed_state
from ._harness import HassetteHarness as HassetteHarness
from ._harness import wait_for as wait_for
from .api_call import ApiCall as ApiCall
from .app_harness import AppConfigurationError as AppConfigurationError
from .app_harness import AppTestHarness as AppTestHarness
from .build_harness import build_harness as build_harness
from .config import make_test_config as make_test_config
from .event_capture import EventCapture as EventCapture
from .exceptions import DrainError as DrainError
from .exceptions import DrainFailure as DrainFailure
from .exceptions import DrainTimeout as DrainTimeout
from .recording_api import RecordingApi as RecordingApi

if TYPE_CHECKING:
    # Type checkers see this as a normal import; __getattr__ below provides it at runtime
    # without requiring `pytest` to be importable just to import this package.
    from .fixtures import dummy_cache as dummy_cache


def __getattr__(name: str) -> object:
    if name == "dummy_cache":
        # house-lint: ignore-next[HSL002] - deliberately lazy: defers the `pytest` import this
        # module needs until `dummy_cache` is actually accessed, not on package import.
        from .fixtures import dummy_cache

        return dummy_cache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "DrainError",
    "DrainFailure",
    "DrainTimeout",
    "EventCapture",
    "HassetteHarness",
    "RecordingApi",
    "build_harness",
    "create_call_service_event",
    "create_state_change_event",
    "dummy_cache",
    "make_full_state_change_event",
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
    "make_typed_state",
    "wait_for",
]

"""Parity test: ApiProtocol must declare every public async method that Api has.

Without this test, future Api method additions can silently skip ApiProtocol
updates. The module-level ``_: ApiProtocol = cast("ApiProtocol", RecordingApi)``
assertion in ``recording_api.py`` is explicitly documented as a Pyright no-op —
it provides structural type-checking but does not enforce that ``ApiProtocol``
is complete.

Uses the same ``vars(cls) + inspect.iscoroutinefunction`` pattern as
``test_recording_api_write_parity.py``. Does NOT use
``ApiProtocol.__annotations__`` because Protocol method declarations
(``async def foo(self) -> None: ...``) do NOT populate ``__annotations__`` —
the dict is empty for pure-method Protocols. A test built on annotation
inspection would always pass vacuously.
"""

import inspect
import sys
from pathlib import Path

from hassette.api.api import Api
from hassette.test_utils.recording_api import ApiProtocol

# Import LIFECYCLE_METHODS from the generator so this test shares the exact same
# set of lifecycle hook names with the generator's filtering logic. This matches
# the pattern used by test_recording_api_write_parity.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))
from generate_sync_facade import LIFECYCLE_METHODS  # noqa: E402


def _public_async_methods(cls: type) -> set[str]:
    """Return public async method names defined directly on cls (not inherited)."""
    return {
        name for name, member in vars(cls).items() if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }


def test_api_protocol_matches_api_methods() -> None:
    """ApiProtocol must declare every public async method that Api has.

    When Api gains a new public async method, ApiProtocol must be updated
    so the module-level ``_: ApiProtocol = cast(...)`` assertion in
    ``recording_api.py`` remains structurally valid and RecordingApi callers
    get accurate Pyright coverage.
    """
    api_methods = _public_async_methods(Api) - LIFECYCLE_METHODS
    protocol_methods = _public_async_methods(ApiProtocol) - LIFECYCLE_METHODS

    missing_from_protocol = api_methods - protocol_methods
    assert not missing_from_protocol, (
        f"ApiProtocol is missing public async methods present in Api: "
        f"{sorted(missing_from_protocol)}. Add them to ApiProtocol in "
        f"src/hassette/test_utils/recording_api.py."
    )


def test_protocol_not_vacuous() -> None:
    """Sanity check: ApiProtocol must declare at least one public async method.

    Without this guard, the main parity test could silently pass if a
    future refactor of ApiProtocol broke method inspection. A non-empty
    method set proves ``_public_async_methods(ApiProtocol)`` is actually
    discovering methods.
    """
    assert len(_public_async_methods(ApiProtocol)) > 0, (
        "_public_async_methods(ApiProtocol) returned an empty set. "
        "The parity test would pass vacuously. Investigate ApiProtocol refactor."
    )

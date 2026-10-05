"""Public paths for the contract enums and Literals defined in `hassette_wire`.

The app-author-facing ones are re-exported from the `hassette` root as the same objects, and
no contract name is re-exported through `hassette.types` or `hassette.schemas` (`__all__` is
checked rather than attribute presence, so those modules may still import a name for their own use).
"""

from hassette_wire import BackpressurePolicy, ExecutionMode, ExecutionStatus, ResourceStatus

import hassette
import hassette.schemas
import hassette.types

# The contract enums and Literals that moved to hassette_wire.
MOVED_CONTRACT_NAMES = (
    "ResourceStatus",
    "AppStatus",
    "ExecutionMode",
    "BackpressurePolicy",
    "ExecutionStatus",
    "SourceTier",
    "LogLevel",
    "QuerySourceTier",
)


def test_hassette_root_reexports_are_identity_with_hassette_wire():
    assert hassette.ExecutionMode is ExecutionMode
    assert hassette.BackpressurePolicy is BackpressurePolicy
    assert hassette.ResourceStatus is ResourceStatus
    assert hassette.ExecutionStatus is ExecutionStatus


def test_no_moved_contract_name_in_old_module_all():
    for module in (hassette.types, hassette.schemas):
        for name in MOVED_CONTRACT_NAMES:
            assert name not in module.__all__, f"{module.__name__}.__all__ still re-exports {name}"

"""Guards the `hassette_wire` move: identity at the `hassette` root, and no moved contract
name re-exported from an old surviving module's public `__all__`.

The contract enums and Literals must be defined only in `hassette_wire`, with the public ones
re-exported as the *same object* from the `hassette` root. `hassette.types` and `hassette.schemas`
are the only old surviving modules that declare `__all__`; a moved contract name appearing in
either would mean it is re-exported from that surface, not just importable via an internal
qualified reference (which `hasattr` can't distinguish from re-export).
"""

from hassette_wire import BackpressurePolicy, ExecutionMode, ExecutionStatus, ResourceStatus

import hassette
import hassette.schemas
import hassette.types

# The contract enums and Literals that moved to hassette_wire.
MOVED_CONTRACT_NAMES = (
    "ResourceStatus",
    "ManifestStatus",
    "ExecutionMode",
    "BackpressurePolicy",
    "ExecutionStatus",
    "SourceTier",
    "LOG_LEVEL_TYPE",
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

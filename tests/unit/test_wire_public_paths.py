"""Guards the `hassette_wire` move: identity at the `hassette` root, no leftover re-exports.

The contract enums and Literals must be defined only in `hassette_wire`, the public ones
re-exported from the `hassette` root, and none of them left on an old `hassette.types*`/
`hassette.schemas` surface.
"""

import hassette_wire

import hassette
import hassette.schemas
import hassette.types
import hassette.types.enums
import hassette.types.types

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

OLD_MODULES = (
    hassette.types,
    hassette.types.enums,
    hassette.types.types,
    hassette.schemas,
)


def test_hassette_root_reexports_are_identity_with_hassette_wire():
    assert hassette.ExecutionMode is hassette_wire.ExecutionMode
    assert hassette.BackpressurePolicy is hassette_wire.BackpressurePolicy
    assert hassette.ResourceStatus is hassette_wire.ResourceStatus
    assert hassette.ExecutionStatus is hassette_wire.ExecutionStatus


def test_no_moved_contract_name_survives_on_old_module_surfaces():
    for module in OLD_MODULES:
        for name in MOVED_CONTRACT_NAMES:
            assert not hasattr(module, name), f"{module.__name__} still exposes {name}"

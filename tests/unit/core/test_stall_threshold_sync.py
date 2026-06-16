"""Guards the deliberate duplication of STALL_THRESHOLD_SECONDS.

The scheduler keeps its own copy of the constant (rather than importing from the bus layer) so the
two subsystems stay decoupled. This test enforces the "kept in sync" contract documented on both
constants: if one value changes, this fails until the other matches.
"""

from hassette.bus.listeners import STALL_THRESHOLD_SECONDS as BUS_STALL_THRESHOLD
from hassette.core.scheduler_service import STALL_THRESHOLD_SECONDS as SCHEDULER_STALL_THRESHOLD


def test_stall_threshold_in_sync() -> None:
    assert SCHEDULER_STALL_THRESHOLD == BUS_STALL_THRESHOLD

"""What one app lifecycle action did to each instance it targeted.

Produced by ``core``'s lifecycle methods (through ``ActionOutcomes``) and mapped to the wire
``InstanceOutcome`` by ``hassette.web``, so it lives here, below both.
"""

from dataclasses import dataclass
from enum import StrEnum


class OutcomeResult(StrEnum):
    """What an action did to one instance."""

    SUCCEEDED = "succeeded"
    """The instance is in the action's target state, including one that already was (see ``reason``)."""

    FAILED = "failed"
    """The action ran on the instance and failed."""

    REFUSED = "refused"
    """The action wasn't run on the instance: it is flagged as needing a hassette restart."""


@dataclass(frozen=True)
class InstanceOutcome:
    """One instance's outcome of one start, stop or reload.

    Valid pairs: ``SUCCEEDED`` with ``needs_restart`` false; ``FAILED`` with ``needs_restart`` true (this action
    flagged the instance) or false; ``REFUSED`` with ``needs_restart`` true.
    """

    instance_index: int
    instance_name: str
    result: OutcomeResult
    needs_restart: bool = False
    """Whether the instance is flagged as needing a hassette restart after this action."""
    reason: str | None = None
    """The failure or refusal, or a note on a success that wasn't plain (``already running``, a reload's
    failed stop)."""

    @property
    def is_newly_flagged(self) -> bool:
        """Whether this action flagged the instance: a failure that left it needing a restart."""
        return self.result is OutcomeResult.FAILED and self.needs_restart

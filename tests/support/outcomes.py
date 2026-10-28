"""An ``ActionOutcomes`` for tests that call a lifecycle internal directly, with no request to declare targets."""

from hassette.core.app_lifecycle_common import ActionOutcomes
from hassette.schemas.app_outcomes import OutcomeResult


class AnyIndexOutcomes(ActionOutcomes):
    """Targets each index the first time an outcome is recorded for it, named ``instance_<index>``.

    For tests that exercise one lifecycle step on its own. A test of the per-request contract (one outcome per
    declared target) goes through a public start/stop/reload instead.
    """

    def __init__(self) -> None:
        super().__init__({})

    def _write(self, index: int, result: OutcomeResult, reason: str | None, *, needs_restart: bool) -> None:
        self.add_targets({index: f"instance_{index}"})
        super()._write(index, result, reason, needs_restart=needs_restart)

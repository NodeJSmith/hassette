"""An ``ActionOutcomes`` for tests that call a lifecycle internal directly, with no request to declare targets."""

from hassette.core.app_lifecycle_common import ActionOutcomes


class AnyIndexOutcomes(ActionOutcomes):
    """Targets each index the first time an outcome is recorded for it, named ``instance_<index>``.

    For tests that exercise one lifecycle step on its own. A test of the per-request contract (one outcome per
    declared target) goes through a public start/stop/reload instead.
    """

    def __init__(self) -> None:
        super().__init__({})

    def succeeded(self, index: int, reason: str | None = None) -> None:
        self.add_targets({index: f"instance_{index}"})
        super().succeeded(index, reason)

    def failed(self, index: int, reason: str, *, needs_restart: bool = False) -> None:
        self.add_targets({index: f"instance_{index}"})
        super().failed(index, reason, needs_restart=needs_restart)

    def refused(self, index: int, reason: str) -> None:
        self.add_targets({index: f"instance_{index}"})
        super().refused(index, reason)

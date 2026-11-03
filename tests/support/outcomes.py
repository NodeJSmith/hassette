"""An ``ActionOutcomes`` for tests that call a lifecycle internal directly, with no request to declare targets."""

from hassette.core.app_lifecycle_common import ActionOutcomes


class AnyNameOutcomes(ActionOutcomes):
    """Targets each instance name the first time an outcome is recorded for it.

    A name's display position is the order in which its first outcome was recorded. For tests that exercise one
    lifecycle step on its own. A test of the per-request contract (one outcome per declared target) goes
    through a public start/stop/reload instead.
    """

    def __init__(self) -> None:
        super().__init__({})

    def target(self, name: str) -> None:
        self.add_targets([name])

    def succeeded(self, name: str, reason: str | None = None) -> None:
        self.target(name)
        super().succeeded(name, reason)

    def failed(self, name: str, reason: str, *, needs_restart: bool = False) -> None:
        self.target(name)
        super().failed(name, reason, needs_restart=needs_restart)

    def refused(self, name: str, reason: str) -> None:
        self.target(name)
        super().refused(name, reason)

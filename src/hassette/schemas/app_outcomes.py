"""What one app lifecycle action did to each instance it targeted.

Produced by ``core``'s lifecycle methods (through ``ActionOutcomes``) and mapped to the wire
``InstanceOutcome`` by ``hassette.web``, so it lives here, below both.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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


def worst_result(outcomes: Iterable[InstanceOutcome]) -> OutcomeResult:
    """An app's batch result: ``FAILED`` if any instance failed, else ``REFUSED`` if any was, else ``SUCCEEDED``."""
    results = {outcome.result for outcome in outcomes}
    if OutcomeResult.FAILED in results:
        return OutcomeResult.FAILED
    if OutcomeResult.REFUSED in results:
        return OutcomeResult.REFUSED
    return OutcomeResult.SUCCEEDED


class ReconcileAction(StrEnum):
    """What a reconcile did to one app as a whole."""

    START = "start"
    """A new app the config added, started."""

    STOP = "stop"
    """An app the config removed or disabled, stopped and not recreated."""

    RELOAD = "reload"
    """An app stopped and recreated: a reload-all's restart, a re-import, or a config change."""


@dataclass(frozen=True)
class AppResult:
    """What a reconcile did to one app: the action, and each instance's outcome of it."""

    action: ReconcileAction
    outcomes: tuple[InstanceOutcome, ...]


@dataclass(frozen=True)
class ReconcileResult:
    """What one reconcile (a file-watcher change or a reload-all) did to each app it stopped, reloaded or started."""

    apps: Mapping[str, AppResult] = field(default_factory=dict)
    """Each affected app's result, by app key."""

    def count(self, result: OutcomeResult) -> int:
        """How many apps' worst instance result is ``result`` (see ``worst_result``)."""
        return sum(1 for app in self.apps.values() if worst_result(app.outcomes) is result)

"""Shared vocabulary for ``AppLifecycleService`` and its mixin modules."""

import typing
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from pathlib import Path

from hassette_wire import ResourceStatus

from hassette.schemas.app_outcomes import InstanceOutcome, OutcomeResult

if typing.TYPE_CHECKING:
    from hassette.config.classes import AppManifest


# Short aliases for ResourceStatus members.
FAILED = ResourceStatus.FAILED
STARTING = ResourceStatus.STARTING
RUNNING = ResourceStatus.RUNNING
STOPPING = ResourceStatus.STOPPING
STOPPED = ResourceStatus.STOPPED
NOT_STARTED = ResourceStatus.NOT_STARTED

# Deeper than the exception_utils.get_short_traceback default (1): init failures often
# surface several frames deep (anyio.fail_after -> on_initialize -> nested awaits), and a
# single frame is rarely enough to show the app's own code rather than just anyio internals.
# Passed as a negative limit (see call sites below) so traceback.format_exc keeps the frames
# closest to the raise — the app author's own code — instead of the frames closest to this
# module's try block.
INIT_FAILURE_TRACEBACK_LIMIT = 5

# Per-manifest upsert timeout. A failed write degrades one app's dashboard row — it must
# never block app startup or a hot-reload. See design doc "Persist trigger".
MANIFEST_UPSERT_TIMEOUT_SECONDS = 5.0

ALREADY_RUNNING_REASON = "already running"
"""A start's or reload's success reason for an instance that was already live."""

ALREADY_STOPPED_REASON = "already stopped"
"""A stop's success reason for a target with nothing tracked to stop."""

CLEARED_FAILURE_REASON = "was not running; cleared its failure"
"""A stop's success reason for a target that held only a failure entry."""

NO_OUTCOME_REASON = "no outcome was recorded"
"""A target's failure reason when nothing recorded an outcome for it and nothing raised."""

NOT_IN_CONFIG_REASON = "the instance is no longer in the app's config"
"""A target's failure reason when its instance was removed from the app's config."""

CLASS_LOAD_FAILED_PREFIX = "the app class failed to load: "
"""Leads a target's failure reason when its app class could not be loaded."""

BAD_CONFIGURATION_PREFIX = "bad configuration: "
"""Leads a target's failure reason when its app's configuration is invalid."""

STOP_FAILED_PREFIX = "the stop before it failed: "
"""Leads the stop half's failure in the reason of a reload that recreated the instance anyway."""


class AppAdmissionMode(StrEnum):
    WAIT_FOR_RELEASE = "wait_for_release"
    REJECT_IF_UNRELEASED = "reject_if_unreleased"


@dataclass
class PendingReconciliation:
    """A deferred app-config reconciliation, queued while bootstrap release hasn't opened yet.

    Presence of an instance (vs. ``None``) on ``AppLifecycleService._pending_reconciliation``
    is the "is one queued?" signal — see ``_record_pre_release_reconciliation`` and
    ``_take_pre_release_reconciliation``, which are the only code that constructs, merges, or
    clears this record.
    """

    original_apps_config: dict[str, "AppManifest"]
    current_apps_config: dict[str, "AppManifest"]
    changed_paths: frozenset[Path] | None


class ActionOutcomes:
    """One lifecycle request's outcome for each instance it targets, one slot per targeted name.

    Each public start, stop and reload creates one once it holds the app-key lock and knows its targets, and
    passes it explicitly down the paths that settle each instance. A slot fills when its outcome is decided, so
    an outcome decided before a sibling or a later step raises is kept. ``finish`` gives every target still
    undecided an outcome, so each target ends with exactly one.

    A reload decides each instance twice, in its stop half and then its create half, which it opens with
    ``begin_create_half``. ``_write`` keeps the rules for combining the two (spec 140 D6).
    """

    def __init__(self, targets: Iterable[str]) -> None:
        """Declare the targets: each targeted instance name, in the order its outcome reports."""
        self._targets = list(dict.fromkeys(targets))
        self._slots: dict[str, InstanceOutcome] = {}
        self._decided: set[str] = set()
        """Names with an outcome from the current half. A reload's create half clears its names from it;
        their slots keep the stop half's outcome until the create half writes over it."""

    def add_targets(self, targets: Iterable[str]) -> None:
        """Target more instances after the existing ones, such as ones a config change added while the action ran."""
        self._targets = list(dict.fromkeys([*self._targets, *targets]))

    @property
    def names(self) -> list[str]:
        """The targeted names, in display order."""
        return list(self._targets)

    def succeeded(self, name: str, reason: str | None = None) -> None:
        """Record that the instance is in the action's target state; ``reason`` notes a success that wasn't plain."""
        self._write(name, OutcomeResult.SUCCEEDED, reason, needs_restart=False)

    def failed(self, name: str, reason: str, *, needs_restart: bool = False) -> None:
        """Record a failure; ``needs_restart`` when this action left the instance flagged as needing a restart."""
        self._write(name, OutcomeResult.FAILED, reason, needs_restart=needs_restart)

    def refused(self, name: str, reason: str) -> None:
        """Record a refusal: the instance was already flagged as needing a hassette restart, so nothing was done."""
        self._write(name, OutcomeResult.REFUSED, reason, needs_restart=True)

    def begin_create_half(self, names: Iterable[str]) -> None:
        """Open a reload's create half: each of ``names`` needs an outcome from it, or ``finish`` fails it."""
        self._decided -= set(names)

    def fail_undecided(self, reason: str, names: Iterable[str] | None = None) -> None:
        """Record ``reason`` as the failure of every target (or each of ``names``) with no outcome from this half."""
        for name in self.names if names is None else names:
            if name not in self._decided:
                self.failed(name, reason)

    def snapshot(self) -> tuple[InstanceOutcome, ...]:
        """The outcomes recorded so far, in display order, leaving targets with none out."""
        return tuple(self._slots[name] for name in self.names if name in self._slots)

    def finish(self, reason: str = NO_OUTCOME_REASON) -> tuple[InstanceOutcome, ...]:
        """Fail every target still undecided with ``reason``, then return every outcome in display order.

        An action whose body raised passes the exception's message as ``reason`` (spec 140 D5).
        """
        self.fail_undecided(reason)
        return self.snapshot()

    def _write(self, name: str, result: OutcomeResult, reason: str | None, *, needs_restart: bool) -> None:
        """Record ``name``'s outcome. A later write replaces an earlier one, unless the earlier one newly flagged it.

        A reload's create half also carries its stop half's failure into the reason it writes.
        """
        if name not in self._targets:
            raise ValueError(f"instance {name!r} is not a target of this action (targets: {self.names})")
        previous = self._slots.get(name)
        first_in_half = name not in self._decided
        self._decided.add(name)
        # A failure that flagged the instance stands: the create half's refusal of the zombie this request
        # created must not relabel it a refusal, and nothing later can make it succeed.
        if previous is not None and previous.is_newly_flagged:
            return
        # A first write in a half over an earlier failure happens only in a reload's create half, so ``previous`` is
        # its stop half's failure, which didn't flag the instance. The create half's result decides (a success means
        # the instance runs), and the stop's failure stays in the reason so it isn't lost.
        if first_in_half and previous is not None and previous.result is OutcomeResult.FAILED:
            reason = "; ".join(part for part in (reason, f"{STOP_FAILED_PREFIX}{previous.reason}") if part)
        self._slots[name] = InstanceOutcome(
            instance_name=name,
            result=result,
            needs_restart=needs_restart,
            reason=reason,
        )


def log_refusals(logger: Logger, app_key: str, outcomes: Iterable[InstanceOutcome]) -> None:
    """Log one ERROR per refused instance, for a start or reload that has no response to carry the refusal.

    HTTP actions report refusals in their response and never log them; every caller without one
    (bootstrap, config and file reconciliation) logs them here, so a refused instance is logged once.
    """
    for outcome in outcomes:
        if outcome.result is OutcomeResult.REFUSED:
            logger.error(
                "Not starting %s (app %r): it %s. Restart hassette to run it again",
                outcome.instance_name,
                app_key,
                outcome.reason,
            )


def failure_reason(exc: BaseException) -> str:
    """An exception's message for an outcome's ``reason``, or its type name when it has none."""
    return str(exc) or type(exc).__name__

"""Turn fetched ``blocking_events`` aggregates into findings: pure grouping, no DB access.

SQL groups attributed events by distinct stored stack and handler; this module classifies each
group's stack and merges groups into one ``BlockingFinding`` per app call site, so each finding is
one thing to fix. Groups with no app-code frame (no stack captured, or written before structured
frames existed) merge per handler instead, marked as having no captured call site. Unattributed
events are summarized for the diagnostics page without crediting any app.
"""

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import PurePath
from typing import Any

from hassette_wire import (
    BlockingFinding,
    BlockingFrameRef,
    BlockingHandlerRef,
    BlockingInstanceRef,
    BlockingTier,
    StackFrame,
    UnattributedBlockingResponse,
    UnattributedStall,
)

from hassette.utils.stack_frames import FrameClassifier, decode_frames

LOGGER = getLogger(__name__)


@dataclass
class _FindingBuilder:
    """Accumulates one finding's groups; groups arrive most recently seen first."""

    app_key: str
    tier: BlockingTier
    call_site: BlockingFrameRef | None
    call_site_is_user_code: bool
    detected_in_package: str | None
    callee: BlockingFrameRef | None
    primitive: str | None
    last_seen_ts: float
    latest_stack: list[StackFrame]
    handlers: dict[tuple[str, int], BlockingHandlerRef] = field(default_factory=dict)
    instances: dict[int, BlockingInstanceRef] = field(default_factory=dict)
    event_count: int = 0
    max_stall_ms: float | None = None
    stall_sum_ms: float = 0.0
    stall_count: int = 0

    def add(self, group: Mapping[str, Any]) -> None:
        self.event_count += group["event_count"]
        # max_stall_ms is NULL only when none of the group's events recorded a stall (Tier 2 rows
        # never do), and then the group adds nothing to any of the three stall aggregates.
        if group["max_stall_ms"] is not None:
            stall = group["max_stall_ms"]
            self.max_stall_ms = stall if self.max_stall_ms is None else max(self.max_stall_ms, stall)
            self.stall_sum_ms += group["stall_sum_ms"]
            self.stall_count += group["stall_count"]
        handler = handler_ref(group)
        if handler is not None:
            self.handlers.setdefault((handler.kind, handler.id), handler)
        index = group["instance_index"]
        self.instances.setdefault(index, BlockingInstanceRef(index=index, name=group["instance_name"]))

    def build(self) -> BlockingFinding:
        return BlockingFinding(
            app_key=self.app_key,
            tier=self.tier,
            call_site=self.call_site,
            call_site_is_user_code=self.call_site_is_user_code,
            detected_in_package=self.detected_in_package,
            callee=self.callee,
            primitive=self.primitive,
            handlers=list(self.handlers.values()),
            instances=sorted(self.instances.values(), key=lambda inst: inst.index),
            event_count=self.event_count,
            max_stall_ms=self.max_stall_ms,
            avg_stall_ms=self.stall_sum_ms / self.stall_count if self.stall_count else None,
            last_seen_ts=self.last_seen_ts,
            latest_stack=self.latest_stack,
        )


def handler_ref(row: Mapping[str, Any]) -> BlockingHandlerRef | None:
    """The listener or job whose execution produced ``row``, or ``None`` when it didn't resolve."""
    if row["listener_id"] is not None and row["listener_name"] is not None:
        return BlockingHandlerRef(
            kind="listener",
            id=row["listener_id"],
            name=row["listener_name"],
            handler_method=row["listener_method"],
            instance_index=row["instance_index"],
        )
    if row["job_id"] is not None and row["job_name"] is not None:
        return BlockingHandlerRef(
            kind="job",
            id=row["job_id"],
            name=row["job_name"],
            handler_method=row["job_method"],
            instance_index=row["instance_index"],
        )
    return None


def classifier_for_apps(app_dirs: Mapping[str, PurePath]) -> Callable[[str | None], FrameClassifier]:
    """Build a lookup from app key to that app's classifier.

    An app missing from the current config (removed since its rows were written), and the
    unattributed case (``None``), get a classifier over every configured app directory.
    """
    union = FrameClassifier.for_current_interpreter(sorted(set(app_dirs.values())))
    per_app = {key: FrameClassifier.for_current_interpreter([d]) for key, d in app_dirs.items()}
    return lambda app_key: per_app.get(app_key, union) if app_key is not None else union


def group_findings(
    groups: Iterable[Mapping[str, Any]], classifier_for: Callable[[str | None], FrameClassifier]
) -> list[BlockingFinding]:
    """Merge per-stack event groups (most recently seen first) into findings, most recently seen first.

    Each group is one distinct stored stack and handler with SQL aggregates over its events
    (``event_count``, ``max_stall_ms``, ``stall_sum_ms``, ``stall_count``, ``last_seen_ts``).
    """
    builders: dict[Hashable, _FindingBuilder] = {}
    unreadable: list[int] = []
    for group in groups:
        app_key: str = group["app_key"]
        frames = decode_frames(group["frames"])
        if frames is None:
            unreadable.append(group["latest_event_id"])
            frames = []
        key, builder = _start_finding(group, app_key, frames, classifier_for(app_key))
        builders.setdefault(key, builder).add(group)
    log_unreadable_frames(unreadable)
    # Dicts keep insertion order and groups arrive most recently seen first, so this is last-seen order.
    return [b.build() for b in builders.values()]


def log_unreadable_frames(event_ids: Sequence[int]) -> None:
    """Report undecodable ``frames`` values once per read, naming one row to inspect."""
    if event_ids:
        LOGGER.warning(
            "blocking_events.frames could not be decoded for %d stack(s); they show as 'call site not captured'",
            len(event_ids),
            extra={"unreadable_count": len(event_ids), "sample_event_id": event_ids[0]},
        )


def _start_finding(
    group: Mapping[str, Any], app_key: str, frames: list[StackFrame], classifier: FrameClassifier
) -> tuple[Hashable, _FindingBuilder]:
    """Return the finding key for ``group`` and a builder seeded from it (used if the key is new).

    A Tier 1 group whose stack holds no app-code frame, and a Tier 2 group with no stored frame,
    both fall through to the per-handler "call site not captured" key at the bottom.
    """
    tier = group["tier"]
    primitive = group["primitive"]
    base = {
        "app_key": app_key,
        "tier": tier,
        "primitive": primitive,
        "last_seen_ts": group["last_seen_ts"],
        "latest_stack": frames,
    }
    if tier == "watchdog":
        idx = classifier.find_call_site(frames)
        if idx is not None:
            site = frames[idx]
            callee = classifier.ref(frames[idx - 1]) if idx > 0 else None
            return (
                ("site", tier, app_key, site.filename, site.lineno),
                _FindingBuilder(
                    **base,
                    call_site=classifier.ref(site),
                    call_site_is_user_code=True,
                    detected_in_package=None,
                    callee=callee,
                ),
            )
    elif frames:
        site = frames[0]
        is_user = classifier.is_user_code(site.filename)
        return (
            ("site", tier, app_key, primitive, site.filename, site.lineno),
            _FindingBuilder(
                **base,
                call_site=classifier.ref(site),
                call_site_is_user_code=is_user,
                detected_in_package=None if is_user else classifier.top_level_package(site),
                callee=None,
            ),
        )
    handler = handler_ref(group)
    handler_key = (handler.kind, handler.id) if handler is not None else None
    return (
        ("uncaptured", tier, app_key, primitive, handler_key),
        _FindingBuilder(**base, call_site=None, call_site_is_user_code=False, detected_in_package=None, callee=None),
    )


def summarize_unattributed(
    totals: Mapping[str, Any], recent_rows: Sequence[Mapping[str, Any]], classifier: FrameClassifier
) -> UnattributedBlockingResponse:
    """Summarize unattributed stalls for the diagnostics page.

    ``totals`` holds the SQL counts and max over the whole window; ``recent_rows`` are the newest
    individual rows, listed with their stacks.
    """
    recent: list[UnattributedStall] = []
    unreadable: list[int] = []
    for row in recent_rows:
        frames = decode_frames(row["frames"])
        if frames is None:
            unreadable.append(row["id"])
            frames = []
        idx = classifier.find_call_site(frames)
        recent.append(
            UnattributedStall(
                detected_ts=row["detected_ts"],
                tier=row["tier"],
                # NULL reason predates migration 007; source_tier='framework' is all it can say.
                reason="displaced" if row["reason"] == "displaced" else "framework",
                stall_duration_ms=row["stall_duration_ms"],
                primitive=row["primitive"],
                app_frame=classifier.ref(frames[idx]) if idx is not None else None,
                stack=frames,
            )
        )
    log_unreadable_frames(unreadable)
    return UnattributedBlockingResponse(
        total_count=totals["total_count"],
        displaced_count=totals["displaced_count"],
        framework_count=totals["total_count"] - totals["displaced_count"],
        max_stall_ms=totals["max_stall_ms"],
        recent=recent,
    )

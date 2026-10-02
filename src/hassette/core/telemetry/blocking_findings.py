"""Turn fetched ``blocking_events`` rows into findings: pure grouping, no DB access.

Attributed rows group into one ``BlockingFinding`` per app call site, so each finding is one
thing to fix. Rows with no app-code frame (no stack captured, or written before structured
frames existed) group per handler instead, marked as having no captured call site. Unattributed
rows are summarized for the diagnostics page without crediting any app.
"""

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from hassette_wire import (
    BlockingFinding,
    BlockingFrameRef,
    BlockingHandlerRef,
    BlockingTier,
    StackFrame,
    UnattributedBlockingResponse,
    UnattributedStall,
)

from hassette.utils.stack_frames import FrameClassifier, decode_frames

# Most recent unattributed stalls listed individually on the diagnostics page.
RECENT_UNATTRIBUTED_LIMIT = 20


@dataclass
class _FindingBuilder:
    """Accumulates one finding's rows; rows arrive newest first."""

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
    stalls: list[float] = field(default_factory=list)
    event_count: int = 0

    def add(self, row: Mapping[str, Any]) -> None:
        self.event_count += 1
        if row["stall_duration_ms"] is not None:
            self.stalls.append(row["stall_duration_ms"])
        handler = handler_ref(row)
        if handler is not None:
            self.handlers.setdefault((handler.kind, handler.id), handler)

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
            event_count=self.event_count,
            max_stall_ms=max(self.stalls) if self.stalls else None,
            avg_stall_ms=sum(self.stalls) / len(self.stalls) if self.stalls else None,
            last_seen_ts=self.last_seen_ts,
            latest_stack=self.latest_stack,
        )


def handler_ref(row: Mapping[str, Any]) -> BlockingHandlerRef | None:
    """The listener or job whose execution produced ``row``, or ``None`` when it didn't resolve."""
    if row["listener_id"] is not None and row["listener_name"] is not None:
        return BlockingHandlerRef(
            kind="listener", id=row["listener_id"], name=row["listener_name"], handler_method=row["listener_method"]
        )
    if row["job_id"] is not None and row["job_name"] is not None:
        return BlockingHandlerRef(kind="job", id=row["job_id"], name=row["job_name"], handler_method=row["job_method"])
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
    rows: Iterable[Mapping[str, Any]], classifier_for: Callable[[str | None], FrameClassifier]
) -> list[BlockingFinding]:
    """Group attributed rows (newest first) into findings, most recently seen first."""
    builders: dict[Hashable, _FindingBuilder] = {}
    for row in rows:
        app_key: str = row["app_key"]
        classifier = classifier_for(app_key)
        frames = decode_frames(row["frames"])
        key, builder = _start_finding(row, app_key, frames, classifier)
        builders.setdefault(key, builder).add(row)
    # Dicts keep insertion order and rows arrive newest first, so this is last-seen order.
    return [b.build() for b in builders.values()]


def _start_finding(
    row: Mapping[str, Any], app_key: str, frames: list[StackFrame], classifier: FrameClassifier
) -> tuple[Hashable, _FindingBuilder]:
    """Return the grouping key for ``row`` and a builder seeded from it (used if the key is new).

    A Tier 1 row whose stack holds no app-code frame, and a Tier 2 row with no stored frame,
    both fall through to the per-handler "call site not captured" key at the bottom.
    """
    tier = row["tier"]
    primitive = row["primitive"]
    base = {
        "app_key": app_key,
        "tier": tier,
        "primitive": primitive,
        "last_seen_ts": row["detected_ts"],
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
    handler = handler_ref(row)
    handler_key = (handler.kind, handler.id) if handler is not None else None
    return (
        ("uncaptured", app_key, handler_key),
        _FindingBuilder(**base, call_site=None, call_site_is_user_code=False, detected_in_package=None, callee=None),
    )


def summarize_unattributed(
    rows: Sequence[Mapping[str, Any]], classifier: FrameClassifier, *, truncated: bool
) -> UnattributedBlockingResponse:
    """Summarize unattributed rows (newest first) for the diagnostics page."""
    displaced = sum(1 for row in rows if row["reason"] == "displaced")
    stalls = [row["stall_duration_ms"] for row in rows if row["stall_duration_ms"] is not None]
    recent: list[UnattributedStall] = []
    for row in rows[:RECENT_UNATTRIBUTED_LIMIT]:
        frames = decode_frames(row["frames"])
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
    return UnattributedBlockingResponse(
        total_count=len(rows),
        displaced_count=displaced,
        framework_count=len(rows) - displaced,
        max_stall_ms=max(stalls) if stalls else None,
        recent=recent,
        truncated=truncated,
    )

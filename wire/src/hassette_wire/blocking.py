"""Blocking-IO findings: calls that blocked the event loop, grouped by the app code to fix.

Stacks are lists of ``StackFrame``, innermost frame first.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict

from hassette_wire.lenient import LenientValue, UnknownValue
from hassette_wire.literals import OpenHandlerKind

BlockingTier = Literal["watchdog", "monkeypatch"]
"""``"watchdog"`` for Tier 1 (loop-stall) events, ``"monkeypatch"`` for Tier 2 (call-site) events."""

OpenBlockingTier = Annotated[BlockingTier | UnknownValue, LenientValue("BlockingTier")]

UnattributedReason = Literal["displaced", "framework"]
"""Why a stall names no app: ``"displaced"`` — an execution was bound but a different task held the
loop, so attribution was withheld; ``"framework"`` — no app execution was responsible."""

OpenUnattributedReason = Annotated[UnattributedReason | UnknownValue, LenientValue("UnattributedReason")]


# blocking_events.frames rows written by every earlier release are decoded with this model, so a
# change must still read them: give a new field a default, and never rename, retype, or make required
# an existing field. A row that fails to decode loses its stack. tests/unit/utils/test_stack_frames.py
# pins the stored shape.
class StackFrame(BaseModel):
    """One captured stack frame."""

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

    filename: str
    """Absolute path of the frame's source file, verbatim from the code object."""
    lineno: int
    function: str
    module: str | None = None
    """The frame's module ``__name__``, or ``None`` when unavailable."""


class BlockingFrameRef(StackFrame):
    """A frame picked out for display, with a short path for summary lines."""

    display_path: str
    """App-code frames relative to their app directory; library frames relative to their
    ``site-packages`` root; stdlib frames as ``stdlib/<path>``; anything else absolute."""


class BlockingHandlerRef(BaseModel):
    """A handler or job whose execution reached a blocking call site."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    kind: OpenHandlerKind
    id: int
    """Listener or scheduled-job row id."""
    name: str
    """Listener name or job name."""
    handler_method: str
    instance_index: int
    """The app instance that registered this handler."""


class BlockingInstanceRef(BaseModel):
    """An app instance whose events are part of a finding."""

    index: int
    name: str | None = None


class BlockingFinding(BaseModel):
    """One thing to fix: every attributed blocking event at the same app call site, grouped.

    ``call_site`` is ``None`` when no app-code frame was captured for these events (no stack
    captured, or the event was recorded without structured frames); such findings are grouped per handler
    instead.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    tier: OpenBlockingTier
    call_site: BlockingFrameRef | None
    """Innermost app-code frame (Tier 1) or the intercepted call's caller frame (Tier 2)."""
    call_site_is_user_code: bool
    """``False`` when a Tier 2 call site is library or stdlib code; see ``detected_in_package``."""
    detected_in_package: str | None = None
    """Top-level package a non-user Tier 2 call site belongs to (e.g. ``"requests"``), else ``None``."""
    callee: BlockingFrameRef | None = None
    """Tier 1 only: the frame just inside the call site — what the app code called into."""
    primitive: str | None = None
    """Tier 2 only: the intercepted primitive, e.g. ``"time.sleep"``."""
    handlers: list[BlockingHandlerRef]
    """Every handler or job whose execution reached this call site, most recently seen first."""
    instances: list[BlockingInstanceRef]
    """The app instances these events came from, by index. A request for every instance merges
    one call site's events across instances into one finding, since they share the code to fix."""
    event_count: int
    max_stall_ms: float | None = None
    """Longest stall in milliseconds. ``None`` for Tier 2, which records no duration."""
    avg_stall_ms: float | None = None
    last_seen_ts: float
    latest_stack: list[StackFrame]
    """The most recent event's captured stack, innermost first. Empty when none was stored."""


class BlockingFindingsResponse(BaseModel):
    """Blocking findings for one app, or for every app."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    findings: list[BlockingFinding]
    """Ordered by most recently seen first."""
    truncated: bool = False
    """``True`` when the cap on findings was hit: the least recently seen call sites are omitted."""


class UnattributedStall(BaseModel):
    """One blocking event that names no app."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    detected_ts: float
    tier: OpenBlockingTier
    reason: OpenUnattributedReason
    stall_duration_ms: float | None = None
    primitive: str | None = None
    app_frame: BlockingFrameRef | None = None
    """Innermost app-code frame in the stack, if any. Shown as evidence, not attribution."""
    stack: list[StackFrame]
    """The captured stack, innermost first. Empty when none was stored."""


class UnattributedBlockingResponse(BaseModel):
    """Loop stalls that no app is credited with."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    total_count: int = 0
    displaced_count: int = 0
    framework_count: int = 0
    max_stall_ms: float | None = None
    recent: list[UnattributedStall]
    """The most recent stalls, newest first."""

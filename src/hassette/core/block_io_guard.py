"""Blocking-I/O detection for the shared event loop.

This module is the canonical location for the shared behavior-resolution logic used
by both Tier 1 (loop-responsiveness watchdog) and Tier 2 (call-site interception).

Architecture reference: design/specs/074-blocking-io-detection/design.md
"""

import asyncio
import builtins
import contextlib
import glob as glob_module
import os
import socket
import threading
import time
import warnings
from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple

from hassette.exceptions import HassetteBlockingIOWarning
from hassette.types.enums import BlockingIOBehavior
from hassette.types.types import BlockingAttributionReason
from hassette.utils.source_capture import capture_source_location

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor, ExecutionMarker

LOGGER = getLogger(__name__)

# Hardcoded fallback when neither per-app nor global config has a value set.
DEFAULT_BLOCKING_IO_BEHAVIOR = BlockingIOBehavior.WARN

# ---------------------------------------------------------------------------
# Saved originals — populated at install, restored at uninstall.
# Tier 2 patches builtins / socket / os, which are PROCESS-GLOBAL: there can be exactly
# one active install per process, and its wrappers close over one specific (hassette,
# executor) pair. A second Hassette instance in the same process therefore cannot install
# its own Tier 2 — it would have to share the first instance's attribution. These globals
# track the single owner so a conflicting second install is reported loudly, not silently.
# Mutated only by install()/uninstall(), which run on the loop thread during
# startup/shutdown (single-threaded); no lock is needed.
# ---------------------------------------------------------------------------

_originals: dict[str, Any] = {}
_installed = False
_owner_id: int | None = None

# Per-thread re-entrancy guard. While a wrapper is mid-detection on this thread, any
# inner patched call passes straight through instead of re-triggering detection. This
# prevents a fatal recursion: emitting a warning can read source via linecache, which
# calls the patched builtins.open on the loop thread → would re-enter without this guard.
_in_wrapper = threading.local()


def resolve_blocking_io_behavior(owner: object) -> BlockingIOBehavior:
    """Resolve the effective ``BlockingIOBehavior`` for the given app owner.

    Resolution order:
    1. ``owner.app_config.blocking_io_behavior`` (per-app, when not ``None``)
    2. ``owner.hassette.config.blocking_io.behavior`` (global, when not ``None``)
    3. ``WARN`` (hardcoded default — FR#7)

    Duck-typed: ``owner`` needs ``app_config.blocking_io_behavior`` and
    ``hassette.config.blocking_io.behavior``. Missing or broken accessors are
    suppressed so detection never crashes a handler.

    Note: the global path is two levels deep (``blocking_io.behavior``, a nested
    config model) — unlike the flat ``forgotten_await_behavior`` that
    ``await_guard.guard_await`` reads. The blocking-IO settings are grouped under
    one nested model, so the global default lives on that model rather than at the
    config root.

    Tier note: this resolves *lazily*, at the moment detection fires — correct for
    Tier 1 (the watchdog has no registration moment) and for Tier 2 (the call site
    is intercepted while the owning app is still alive). It must NOT be deferred to
    a teardown path (e.g. ``__del__``) where the owner's config may be gone; resolve
    while the owner is live, exactly as ``guard_await`` does eagerly.

    Args:
        owner: The owning App resource, or any object with the duck-typed interface above.

    Returns:
        The resolved ``BlockingIOBehavior`` for this app.
    """
    behavior: BlockingIOBehavior = DEFAULT_BLOCKING_IO_BEHAVIOR
    with contextlib.suppress(AttributeError, ValueError, TypeError):
        per_app = getattr(getattr(owner, "app_config", None), "blocking_io_behavior", None)
        if per_app is not None:
            behavior = BlockingIOBehavior(per_app)
        else:
            hassette_cfg = getattr(getattr(owner, "hassette", None), "config", None)
            global_val = getattr(getattr(hassette_cfg, "blocking_io", None), "behavior", None)
            if global_val is not None:
                behavior = BlockingIOBehavior(global_val)
    return behavior


# ---------------------------------------------------------------------------
# Tier 2 event structure (for T05 to consume)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonkeypatchEvent:
    """Detected blocking call event — structured for T05 DB persistence.

    Carries enough attribution that the persistence layer (T05) can write a
    ``blocking_events`` row without re-reading any live state.

    ``tier`` is always ``"monkeypatch"`` for Tier 2 events.
    """

    primitive: str
    """Name of the blocking primitive that was intercepted (e.g. ``"time.sleep"``)."""

    source_location: str
    """``"<file>:<lineno>"`` of the first non-hassette caller frame."""

    app_key: str | None
    """App key whose execution triggered the call, or ``None`` for framework/unattributed."""

    instance_name: str | None
    """Human-readable instance name, or ``None``."""

    instance_index: int | None
    """0-based instance index, or ``None`` when the marker had none."""

    execution_id: str | None
    """UUIDv7 string of the execution that made the call, or ``None`` when no marker."""

    tier: str
    """Always ``"monkeypatch"`` for Tier 2 events."""

    detected_at: float
    """``time.time()`` wall-clock timestamp when the call was intercepted."""

    reason: BlockingAttributionReason
    """Attribution outcome: ``"attributed"`` (the marker's task made this call), ``"displaced"``
    (a marker was bound but a different task — or no task — made the call, so ``app_key`` was
    withheld), or ``"framework"`` (no execution was bound: a genuine framework/library call)."""


# ---------------------------------------------------------------------------
# Enablement logic (FR#6, AC#10)
# ---------------------------------------------------------------------------


def _should_install(hassette: "Hassette") -> bool:
    """Decide whether Tier 2 should be installed, mirroring allow_reload_in_prod precedent."""
    cfg = hassette.config
    enabled: bool | None = cfg.blocking_io.deep_detection_enabled
    if enabled is None:
        enabled = cfg.dev_mode  # None → follow dev_mode
    if not enabled:
        return False  # explicitly disabled
    if cfg.dev_mode:
        return True  # dev: on
    return cfg.blocking_io.allow_deep_detection_in_prod  # prod: only with explicit opt-in


# ---------------------------------------------------------------------------
# Wrapper factory
# ---------------------------------------------------------------------------


def _detect(primitive_name: str, hassette: "Hassette", executor: "CommandExecutor") -> None:
    """Resolve attribution for a loop-thread blocking call, build the event, and emit.

    On WARN/ERROR this calls ``warnings.warn``, which RAISES if the active filter escalates
    ``HassetteBlockingIOWarning`` to an error (the dev-mode / AC#5 case). The caller places
    this BEFORE invoking the original primitive, so a raised warning intercepts the call —
    the original never runs. ``IGNORE`` returns without emitting (the original then runs).
    """
    marker = executor.current_execution
    app_key, instance_name, instance_index, execution_id, reason = _confirm_attribution(marker)
    # Resolve the owner App from the *confirmed* app_key (None for displaced/framework), so a
    # displaced call resolves behavior from global config, not the innocent marker app's setting.
    owner = _resolve_owner(hassette, app_key, instance_index)
    behavior = resolve_blocking_io_behavior(owner)
    if behavior is BlockingIOBehavior.IGNORE:
        return

    event = MonkeypatchEvent(
        primitive=primitive_name,
        # frames_to_skip=0 is correct: find_caller_frame strips all hassette frames (this
        # module and the wrapper included) by module name, landing on the app call site.
        source_location=capture_source_location(frames_to_skip=0),
        app_key=app_key,
        instance_name=instance_name,
        instance_index=instance_index,
        execution_id=execution_id,
        tier="monkeypatch",
        detected_at=time.time(),
        reason=reason,
    )
    # Persist BEFORE emitting (T05). _emit can raise (a filterwarnings("error") escalation that
    # intercepts the call), which would otherwise skip the row — but the call was detected and
    # must be recorded. record_blocking_event() is best-effort: it enqueues the write fire-and-forget
    # and drops the row (no raise) if the DB queue isn't live yet. The _in_wrapper.active
    # guard is still set, so any patched primitive the DB machinery touches passes straight through.
    executor.record_blocking_event(event)
    _emit(event)


def _make_module_wrapper(
    primitive_name: str,
    original: Any,
    loop_thread_id: int,
    hassette: "Hassette",
    executor: "CommandExecutor",
) -> Any:
    """Build a wrapper for a module-level blocking function (open, time.sleep, os.*, glob.glob)."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Off-loop (executor offload, FR#8/AC#4) or re-entrant (inside our own warn/emit path):
        # pass straight through to the original.
        if threading.get_ident() != loop_thread_id or getattr(_in_wrapper, "active", False):
            return original(*args, **kwargs)
        _in_wrapper.active = True
        try:
            # _detect may raise (warn escalated by the user's filter); then the original is
            # never reached — that is the "raise before the call" interception guarantee.
            _detect(primitive_name, hassette, executor)
            return original(*args, **kwargs)
        finally:
            _in_wrapper.active = False

    return wrapper


def _make_method_wrapper(
    primitive_name: str,
    original: Any,
    loop_thread_id: int,
    hassette: "Hassette",
    executor: "CommandExecutor",
) -> Any:
    """Build a wrapper for a socket method (connect/recv/send).

    Same semantics as ``_make_module_wrapper`` but forwards ``self`` (it replaces a method on
    the ``socket.socket`` type). It also skips non-blocking sockets: asyncio's own transports
    call ``recv``/``send``/``connect`` on non-blocking sockets on the loop thread, and those do
    not stall the loop, so flagging them would be a false-positive storm. Only blocking sockets
    (``getblocking()`` True) are real loop-stalling calls.
    """

    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if threading.get_ident() != loop_thread_id or getattr(_in_wrapper, "active", False):
            return original(self, *args, **kwargs)
        # Non-blocking sockets (asyncio transports) never stall the loop — pass through.
        # A closed or errored socket (getblocking() raises, e.g. OSError "Bad file descriptor"
        # on a closed asyncio internal socket) also passes through: it cannot be meaningfully
        # stalling the loop. Catch broadly so a getblocking failure never becomes a false positive.
        try:
            blocking = self.getblocking()
        except Exception:
            return original(self, *args, **kwargs)
        if not blocking:
            return original(self, *args, **kwargs)
        _in_wrapper.active = True
        try:
            _detect(primitive_name, hassette, executor)
            return original(self, *args, **kwargs)
        finally:
            _in_wrapper.active = False

    return wrapper


# ---------------------------------------------------------------------------
# Attribution helper
# ---------------------------------------------------------------------------


class _Attribution(NamedTuple):
    """Resolved attribution for one detected blocking call. The first four fields are ``None``
    unless ``reason == "attributed"`` (a displaced/framework call carries no owner)."""

    app_key: str | None
    instance_name: str | None
    instance_index: int | None
    execution_id: str | None
    reason: BlockingAttributionReason


def _confirm_attribution(marker: "ExecutionMarker | None") -> _Attribution:
    """Confirm the marker names the task making this blocking call.

    Tier 2 runs inline on the loop thread in the *same task* as the blocking call, so reading the
    marker is already accurate in the common case. The ``task_id`` check only withholds attribution
    on a *positive* mismatch: a different task is currently running than the one that bound the
    marker, which means the marker's execution yielded and a displacing task made the call. When
    there is no current task (a bare loop callback, or no running loop), the marker is trusted —
    the inline read is reliable there and withholding would lose correct attributions.

    Note the deliberate asymmetry with Tier 1's ``_classify_attribution``: when the marker was
    bound outside any task (``task_id is None``) Tier 2 *trusts* it (the inline read is in the
    blocker's own call chain), whereas Tier 1 *withholds* (it reads cross-thread and cannot
    confirm). No marker at all is a genuine framework/library call.
    """
    if marker is None:
        return _Attribution(None, None, None, None, "framework")
    try:
        current = asyncio.current_task()
    except RuntimeError:
        current = None  # no running loop on this thread — fall through to trusting the marker
    if current is not None and marker.task_id is not None and id(current) != marker.task_id:
        # A different task displaced the marker's execution and made this call — withhold.
        return _Attribution(None, None, None, None, "displaced")
    return _Attribution(marker.app_key, marker.instance_name, marker.instance_index, marker.execution_id, "attributed")


def _resolve_owner(hassette: "Hassette", app_key: str | None, instance_index: int | None) -> object:
    """Resolve the owning App instance for behavior resolution, or ``hassette`` when unattributed."""
    if app_key is None:
        return hassette
    with contextlib.suppress(Exception):
        app_inst = hassette.app_handler.get(app_key, instance_index or 0)
        if app_inst is not None:
            return app_inst
    return hassette


# ---------------------------------------------------------------------------
# Warning emission
# ---------------------------------------------------------------------------


def _emit(event: MonkeypatchEvent) -> None:
    """Emit the warning for a detected blocking call.

    ERROR is not a distinct code path here: WARN and ERROR both call ``warnings.warn`` with the
    same arguments. Whether the warning escalates to a raised exception depends entirely on the
    user's ``filterwarnings`` config (dev_mode installs ``filterwarnings("error")``); the guard
    never raises unconditionally (FR#7). Mirrors the Tier 1 watchdog's ``_emit`` method.
    """
    app_label = event.app_key or "<framework>"
    inst_label = f" ({event.instance_name})" if event.instance_name else ""
    msg = (
        f"Blocking I/O detected on the event loop (Tier 2 — call-site interception) — "
        f"primitive: {event.primitive}, "
        f"app: {app_label}{inst_label}, "
        f"call site: {event.source_location}"
    )
    if event.execution_id:
        msg += f", execution: {event.execution_id}"
    # stacklevel=1: the real call site is captured in source_location; the frame
    # that would be named by stacklevel is the wrapper itself (unhelpful).
    warnings.warn(msg, HassetteBlockingIOWarning, stacklevel=1)


# ---------------------------------------------------------------------------
# Curated primitive table
# ---------------------------------------------------------------------------
# Two patch styles:
#   - module-level: (module_obj, attr_name, original_callable)
#   - method: (class_obj, attr_name, original_callable)  — wrapper needs self
#
# Seeded from HA's block_async_io.py.

_PRIMITIVE_TABLE: list[tuple[str, Any, str]] = [
    # (primitive_label, target_object, attr_name)
    ("builtins.open", builtins, "open"),
    ("time.sleep", time, "sleep"),
    ("os.listdir", os, "listdir"),
    ("os.scandir", os, "scandir"),
    ("os.walk", os, "walk"),
    ("glob.glob", glob_module, "glob"),
]

_SOCKET_METHOD_TABLE: list[tuple[str, str]] = [
    # (primitive_label, method_name_on_socket.socket)
    ("socket.socket.connect", "connect"),
    ("socket.socket.recv", "recv"),
    ("socket.socket.send", "send"),
]


# ---------------------------------------------------------------------------
# Install / uninstall (idempotent, reversible, leak-proof)
# ---------------------------------------------------------------------------


def install(hassette: "Hassette", *, loop_thread_id: int, executor: "CommandExecutor") -> bool:
    """Install Tier 2 call-site interception.

    Idempotent for a single owner: a second call without an intervening ``uninstall`` is a
    no-op. Returns ``True`` when patches were installed, ``False`` when the call was a no-op
    (already installed or disabled by config). Tier 2 is process-global; a second call from a
    *different* Hassette instance logs a warning and is refused (that instance gets no Tier 2).

    Args:
        hassette: The running Hassette instance.
        loop_thread_id: ``threading.get_ident()`` captured on the loop thread.
        executor: The ``CommandExecutor`` whose ``current_execution`` marker
            is read for app attribution.
    """
    global _installed, _owner_id
    if _installed:
        if _owner_id != id(hassette):
            LOGGER.warning(
                "Tier 2 blocking-IO guard is already installed by another Hassette instance in "
                "this process; this instance will not get call-site interception. Tier 2 patches "
                "builtins/socket/os, which are process-global and cannot be owned by two instances."
            )
        return False
    if not _should_install(hassette):
        return False

    # Mark installed BEFORE patching so a mid-install failure can be rolled back by uninstall()
    # (which no-ops when not installed). Otherwise a partial patch would be permanent.
    _installed = True
    _owner_id = id(hassette)
    try:
        # Install module-level wrappers.
        for label, target, attr in _PRIMITIVE_TABLE:
            original = getattr(target, attr)
            _originals[label] = original
            setattr(target, attr, _make_module_wrapper(label, original, loop_thread_id, hassette, executor))

        # Install socket method wrappers.
        for label, method_name in _SOCKET_METHOD_TABLE:
            original = getattr(socket.socket, method_name)
            _originals[label] = original
            setattr(
                socket.socket,
                method_name,
                _make_method_wrapper(label, original, loop_thread_id, hassette, executor),
            )
    except Exception:
        uninstall()  # restore whatever was already patched, then re-raise
        raise
    return True


def uninstall(hassette: "Hassette | None" = None) -> bool:
    """Restore every patched primitive to its original.

    Idempotent: calling when not installed is a no-op.

    Owner-aware: Tier 2 is process-global with a single owning instance. When ``hassette``
    is passed and is not the owner, this no-ops and leaves the patches in place so a
    non-owning instance's shutdown cannot disable call-site interception for the still-running
    owner. Pass ``None`` (the default) to force an unconditional restore — used by tests and
    by rollback inside ``install()``.

    Returns ``True`` when originals were restored, ``False`` when not installed or the caller
    is not the owner.
    """
    global _installed, _owner_id
    if not _installed:
        return False
    if hassette is not None and _owner_id != id(hassette):
        LOGGER.warning(
            "Tier 2 blocking-IO guard uninstall requested by a non-owner Hassette instance; "
            "leaving process-global patches installed for the owning instance."
        )
        return False

    # Restore module-level originals.
    for label, target, attr in _PRIMITIVE_TABLE:
        original = _originals.get(label)
        if original is not None:
            setattr(target, attr, original)

    # Restore socket method originals.
    for label, method_name in _SOCKET_METHOD_TABLE:
        original = _originals.get(label)
        if original is not None:
            setattr(socket.socket, method_name, original)

    _originals.clear()
    _installed = False
    _owner_id = None
    return True


def is_installed() -> bool:
    """Return True when Tier 2 patches are currently active."""
    return _installed

import inspect
import typing
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from logging import getLogger
from typing import Any, TypeVar

from hassette.exceptions import HassetteNotInitializedError

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig, TaskBucket

LOGGER = getLogger(__name__)

CURRENT_BUCKET: ContextVar["TaskBucket | None"] = ContextVar("CURRENT_BUCKET", default=None)
PROTECT_TASK: ContextVar[bool] = ContextVar("PROTECT_TASK", default=False)
"""When True in the ambient context at task-creation time, make_task_factory()'s factory
skips bucket registration for that task entirely -- it is never added to any TaskBucket, so
no cancel_all()/cancel_all_sync() on any bucket can ever cancel it as a side effect. Checked
at creation time (inside the loop's task factory), not at cancellation time: Task.get_context()
(needed to inspect another task's own bound context from outside it) was only added in Python
3.12, and this project supports 3.11+, so cancellation-time inspection isn't viable here. Reading
the *ambient* ContextVar at creation time works on every supported version, the same way
CURRENT_BUCKET already does in the same factory.

Exists for callers (a test's own top-level task; a caller whose task would otherwise end up
incidentally tracked in a bucket it doesn't own or control) that must not be swept up by an
unrelated cancel_all() elsewhere.

Set with a bare ``PROTECT_TASK.set(True)``, not a scoped context manager: the intended caller
(a pytest fixture) sets this in one task and needs it to still read True at *creation time for
a different, not-yet-created task* (the test body's own task) that pytest-asyncio's
contextvar-propagation machinery copies the value into after this task finishes. A ``with``-style
helper that resets on exit would clear the value before that propagation ever happens, silently
defeating the whole mechanism."""
CURRENT_EXECUTION_ID: ContextVar[str | None] = ContextVar("CURRENT_EXECUTION_ID", default=None)
"""UUIDv7 set for the duration of each handler/job execution. Spawned sub-tasks inherit a snapshot
of this value at creation time; the snapshot is NOT cleared when the originating execution ends."""
HASSETTE_INSTANCE: ContextVar["Hassette"] = ContextVar("HASSETTE_INSTANCE")
HASSETTE_SET_LOCATION: ContextVar[str | None] = ContextVar("HASSETTE_SET_LOCATION", default=None)
HASSETTE_CONFIG: ContextVar["HassetteConfig"] = ContextVar("HASSETTE_CONFIG")

T = TypeVar("T")


def set_global_hassette(hassette: "Hassette") -> "Token[Hassette] | None":
    """Set the global Hassette instance.

    Returns the Token from ContextVar.set() so the caller can later reset the
    ContextVar (e.g., test harnesses that need to undo the context after teardown).
    Returns None when the same instance is already set (early-return path — no token
    is produced because no set() call was made).

    Raises RuntimeError if a different Hassette instance is already set.
    """
    current_instance = HASSETTE_INSTANCE.get(None)
    if current_instance is hassette:
        return None  # already set to the same instance

    if current_instance is not None:
        extra_msg = f"Set at {HASSETTE_SET_LOCATION.get()}" if HASSETTE_SET_LOCATION.get() else ""
        raise RuntimeError(f"Hassette instance is already set. {extra_msg}".rstrip())

    try:
        # Capture where this was first set
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        if caller is not None:
            info = inspect.getframeinfo(caller)
            where = f"{info.filename}:{info.lineno} in {info.function}"
        else:
            where = "<unknown location>"
    except Exception as exc:
        LOGGER.warning("Failed to capture set location for Hassette instance: %s", exc)
        where = "<unknown location>"

    HASSETTE_SET_LOCATION.set(where)
    return HASSETTE_INSTANCE.set(hassette)


def set_global_hassette_config(config: "HassetteConfig") -> None:
    """Set the global HassetteConfig instance. This can be overridden using the `use` context manager."""
    if HASSETTE_CONFIG.get(None) is not None:
        raise RuntimeError("HassetteConfig is already set in context.")
    HASSETTE_CONFIG.set(config)


def get_hassette() -> "Hassette":
    """Get the current Hassette instance from context."""
    try:
        inst = HASSETTE_INSTANCE.get()
        return inst
    except LookupError as exc:
        raise HassetteNotInitializedError("No Hassette instance found in context.") from exc


def get_hassette_config() -> "HassetteConfig":
    """Get the current Hassette configuration from context."""
    try:
        config = HASSETTE_CONFIG.get()
        return config
    except LookupError:
        LOGGER.debug("HassetteConfig not found in context, attempting to get from Hassette instance.")
        return get_hassette().config


@contextmanager
def use(var: ContextVar[T], value: T) -> Generator[None, Any, Any]:
    """Temporarily set a ContextVar to `value` within a block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)


@contextmanager
def use_hassette_config(config: "HassetteConfig") -> Generator[None, Any, Any]:
    """Temporarily set the global HassetteConfig within a block."""
    token = HASSETTE_CONFIG.set(config)
    try:
        yield
    finally:
        HASSETTE_CONFIG.reset(token)


@contextmanager
def use_task_bucket(bucket: "TaskBucket") -> Generator[None, Any, Any]:
    """Temporarily set the current TaskBucket within a block."""
    token = CURRENT_BUCKET.set(bucket)
    try:
        yield
    finally:
        CURRENT_BUCKET.reset(token)

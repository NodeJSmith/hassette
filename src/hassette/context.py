import inspect
import typing
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from logging import getLogger
from typing import Any, TypeVar

from hassette.exceptions import HassetteNotInitializedError

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig, TaskBucket

LOGGER = getLogger(__name__)

CURRENT_BUCKET: ContextVar["TaskBucket | None"] = ContextVar("CURRENT_BUCKET", default=None)
HASSETTE_INSTANCE: ContextVar["Hassette"] = ContextVar("HASSETTE_INSTANCE")
HASSETTE_SET_LOCATION: ContextVar[str | None] = ContextVar("HASSETTE_SET_LOCATION", default=None)
HASSETTE_CONFIG: ContextVar["HassetteConfig"] = ContextVar("HASSETTE_CONFIG")

T = TypeVar("T")

## Setters ##


def set_global_hassette(hassette: "Hassette") -> None:
    """Set the global Hassette instance."""
    curr_inst = HASSETTE_INSTANCE.get(None)
    if curr_inst is hassette:
        return  # already set to the same instance

    if curr_inst is not None:
        extra_msg = f"Set at {HASSETTE_SET_LOCATION.get()}" if HASSETTE_SET_LOCATION.get() else ""
        raise RuntimeError(f"Hassette instance is already set.{extra_msg}")

    try:
        # Capture where this was first set
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        if caller is not None:
            info = inspect.getframeinfo(caller)
            where = f"{info.filename}:{info.lineno} in {info.function}"
        else:
            where = "<unknown location>"
    except Exception as e:
        LOGGER.warning("Failed to capture set location for Hassette instance: %s", e)
        where = "<unknown location>"

    HASSETTE_SET_LOCATION.set(where)
    HASSETTE_INSTANCE.set(hassette)


def set_global_hassette_config(config: "HassetteConfig") -> None:
    """Set the global HassetteConfig instance. This can be overriden using the `use` context manager."""
    if HASSETTE_CONFIG.get(None) is not None:
        raise RuntimeError("HassetteConfig is already set in context.")
    HASSETTE_CONFIG.set(config)


## Getters ##


def get_hassette() -> "Hassette":
    """Get the current Hassette instance from context."""
    try:
        inst = HASSETTE_INSTANCE.get()
        return inst
    except LookupError as e:
        raise HassetteNotInitializedError("No Hassette instance found in context.") from e


def get_hassette_config() -> "HassetteConfig":
    """Get the current Hassette configuration from context."""
    try:
        config = HASSETTE_CONFIG.get()
        return config
    except LookupError as e:
        LOGGER.debug("HassetteConfig not found in context, attempting to get from Hassette instance.")
        c = get_hassette().config
        if c is None:
            raise HassetteNotInitializedError("No HassetteConfig found in context or Hassette instance.") from e
        return c


## Context Managers ##


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

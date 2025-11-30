import inspect
import typing
from collections.abc import Generator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from logging import getLogger
from typing import Any

from hassette.exceptions import HassetteNotInitializedError

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig, TaskBucket
    from hassette.core.state_registry import StateRegistry

LOGGER = getLogger(__name__)

CURRENT_BUCKET: ContextVar["TaskBucket | None"] = ContextVar("CURRENT_BUCKET", default=None)
HASSETTE_INSTANCE: ContextVar["Hassette"] = ContextVar("HASSETTE_INSTANCE")
HASSETTE_CONFIG: ContextVar["HassetteConfig"] = ContextVar("HASSETTE_CONFIG")
HASSETTE_STATE_REGISTRY: ContextVar["StateRegistry"] = ContextVar("HASSETTE_STATE_REGISTRY")
HASSETTE_SET_LOCATION: ContextVar[str | None] = ContextVar("HASSETTE_SET_LOCATION", default=None)


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
    except LookupError:
        LOGGER.error("HassetteConfig not found in context, attempting to get from Hassette instance.")
        return get_hassette().config


def get_state_registry() -> "StateRegistry":
    """Get the current StateRegistry from the Hassette instance in context."""
    try:
        registry = HASSETTE_STATE_REGISTRY.get()
        return registry
    except LookupError:
        LOGGER.error("StateRegistry not found in context, attempting to get from Hassette instance.")
        return get_hassette().state_registry


def set_global_hassette(hassette: "Hassette") -> None:
    """Set the global Hassette instance."""
    curr_inst = None
    with suppress(LookupError):
        curr_inst = HASSETTE_INSTANCE.get()
        if curr_inst is hassette:
            return  # already set to the same instance

    if HASSETTE_INSTANCE.get(None) is not None:
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


def set_global_state_registry(registry: "StateRegistry") -> None:
    """Set the global StateRegistry instance. This can be overriden using the `use` context manager."""
    if HASSETTE_STATE_REGISTRY.get(None) is not None:
        raise RuntimeError("StateRegistry is already set in context.")
    HASSETTE_STATE_REGISTRY.set(registry)


@contextmanager
def use[T](var: ContextVar[T], value: T) -> Generator[None, Any]:
    """Temporarily set a ContextVar to `value` within a block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)


@contextmanager
def use_hassette_config(config: "HassetteConfig") -> Generator[None, Any]:
    """Temporarily set the global HassetteConfig within a block."""
    token = HASSETTE_CONFIG.set(config)
    try:
        yield
    finally:
        HASSETTE_CONFIG.reset(token)


@contextmanager
def use_task_bucket(bucket: "TaskBucket") -> Generator[None, Any]:
    """Temporarily set the current TaskBucket within a block."""
    token = CURRENT_BUCKET.set(bucket)
    try:
        yield
    finally:
        CURRENT_BUCKET.reset(token)


@contextmanager
def use_state_registry(registry: "StateRegistry") -> Generator[None, Any]:
    """Temporarily set the global StateRegistry within a block."""
    token = HASSETTE_STATE_REGISTRY.set(registry)
    try:
        yield
    finally:
        HASSETTE_STATE_REGISTRY.reset(token)

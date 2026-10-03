"""Helpers shared by the wire tests for recognizing Open<TypeName> aliases."""

import importlib
import pkgutil
from typing import Annotated, Any, get_args, get_origin

import hassette_wire
from hassette_wire import UnknownValue
from hassette_wire.lenient import LenientValue


def is_open_alias(obj: Any) -> bool:
    """Whether ``obj`` is an ``Annotated`` alias carrying a ``LenientValue`` marker."""
    return get_origin(obj) is Annotated and any(isinstance(meta, LenientValue) for meta in obj.__metadata__)


def plain_type(alias: Any) -> Any:
    """The enum or Literal arm behind an Open<TypeName> alias (the shape ``known_arm`` enforces)."""
    union = get_args(alias)[0]
    return next(arm for arm in get_args(union) if arm is not UnknownValue)


def open_aliases() -> dict[str, Any]:
    """Every Open<TypeName> alias in any hassette_wire submodule, by name."""
    return {
        name: obj
        for module_info in pkgutil.iter_modules(hassette_wire.__path__)
        for name, obj in vars(importlib.import_module(f"hassette_wire.{module_info.name}")).items()
        if is_open_alias(obj)
    }

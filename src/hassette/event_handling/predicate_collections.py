"""Flattening helpers for predicate collections passed as ``where=`` clauses."""

import typing
from collections.abc import Mapping, Sequence
from typing import Any, TypeGuard

from boltons.iterutils import is_collection

if typing.TYPE_CHECKING:
    from hassette.types import Predicate


def ensure_tuple(where: "Predicate | Sequence[Predicate]") -> tuple["Predicate", ...]:
    """Ensure the 'where' is a flat tuple of predicates, flattening *only* predicate collections.

    Recurses into list/tuple/set/frozenset; leaves Mapping, strings/bytes, and callables intact.
    """
    if is_predicate_collection(where):
        out: list[Predicate] = []
        # mypy/pyright: guarded by _is_predicate_collection, so safe to iterate
        for item in typing.cast("Sequence[Predicate | Sequence[Predicate]]", where):
            out.extend(ensure_tuple(item))
        return tuple(out)

    return (typing.cast("Predicate", where),)


def is_predicate_collection(obj: Any) -> TypeGuard[Sequence["Predicate"]]:
    """Return True for *predicate collections* we want to recurse into.

    We treat only list/tuple/set/frozenset-like things as collections of predicates.
    We explicitly DO NOT recurse into:
      - mappings (those feed ServiceDataWhere elsewhere),
      - strings/bytes,
      - callables (predicates are callables; don't explode them),
      - None.
    """
    if obj is None:
        return False
    if callable(obj):
        return False
    if isinstance(obj, (str, bytes, Mapping)):
        return False
    # boltons.is_collection filters out scalars for us; we just fence off types we don't want
    return is_collection(obj)

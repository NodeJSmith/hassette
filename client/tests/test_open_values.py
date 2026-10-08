"""Every value a client method returns tolerates a newer server's new enum or ``Literal`` values.

A closed field that gains a value makes an older client raise ``ResponseValidationError``, and for a
write that happens after the server has already acted. So any enum or ``Literal`` reachable from a
:class:`~hassette_client.HassetteClient` return type must be an ``Open<TypeName>`` alias, single-value
status fields included, except the vocabularies the wire contract declares closed.
"""

import inspect
from enum import Enum
from typing import Any, Literal, get_args, get_origin, get_type_hints

from hassette_client import HassetteClient
from hassette_wire.lenient import LenientValue
from hassette_wire.literals import CLOSED_VOCABULARIES
from pydantic import BaseModel


def is_open(metadata: Any) -> bool:
    return any(isinstance(meta, LenientValue) for meta in metadata)


def closed_vocabularies(annotation: Any, where: str, seen: set[type[BaseModel]]) -> list[str]:
    """Each closed enum or ``Literal`` reachable from ``annotation``, as ``"<where>: <type>"``.

    ``seen`` is shared across calls, so a model reached from several methods is walked, and reported, once.
    """
    if hasattr(annotation, "__metadata__") and is_open(annotation.__metadata__):
        return []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return []
        seen.add(annotation)
        return [
            found
            for name, field in annotation.model_fields.items()
            if not is_open(field.metadata)
            for found in closed_vocabularies(field.annotation, f"{annotation.__name__}.{name}", seen)
        ]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [f"{where}: {annotation.__name__}"]
    if get_origin(annotation) is Literal:
        return [] if any(annotation == closed for closed in CLOSED_VOCABULARIES) else [f"{where}: {annotation}"]
    return [found for arg in get_args(annotation) for found in closed_vocabularies(arg, where, seen)]


def test_every_returned_vocabulary_is_open() -> None:
    seen: set[type[BaseModel]] = set()
    closed = [
        found
        for name, method in inspect.getmembers(HassetteClient, inspect.iscoroutinefunction)
        if not name.startswith("_")
        for found in closed_vocabularies(get_type_hints(method, include_extras=True)["return"], name, seen)
    ]

    # A floor well under today's count, so a broken model walk fails instead of passing vacuously.
    assert len(seen) >= 25, f"walked only {len(seen)} models"
    assert closed == []

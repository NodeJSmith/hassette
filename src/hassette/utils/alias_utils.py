from collections.abc import Sequence
from functools import cache
from typing import Any

from pydantic import AliasChoices, BaseModel
from pydantic.fields import FieldInfo


def str_aliases(info: FieldInfo) -> tuple[str, ...]:
    """Return the string aliases pydantic validates `info`'s field by, in lookup order.

    A ``validation_alias`` replaces ``alias`` for validation, so only one of them counts. ``AliasPath`` choices
    are ignored.
    """
    alias = info.validation_alias or info.alias
    choices = alias.choices if isinstance(alias, AliasChoices) else (alias,)
    return tuple(c for c in choices if isinstance(c, str))


@cache
def alias_groups(model: type[BaseModel]) -> tuple[tuple[str, ...], ...]:
    """Return each multi-spelling field's string aliases in pydantic's lookup order; the first is canonical.

    ``AliasPath`` choices are ignored, and fields with fewer than two string spellings are omitted.
    """
    groups: list[tuple[str, ...]] = []
    for info in model.model_fields.values():
        names = str_aliases(info)
        if len(names) > 1:
            groups.append(names)
    return tuple(groups)


def canonicalize_aliases(data: dict[str, Any], groups: Sequence[tuple[str, ...]]) -> dict[str, Any]:
    """Rewrite alias keys to each group's canonical spelling; if several are present, the first in order wins."""
    out = dict(data)
    for group in groups:
        present = [k for k in group if k in out]
        if present and present != [group[0]]:
            value = out[present[0]]
            for key in present:
                del out[key]
            out[group[0]] = value
    return out

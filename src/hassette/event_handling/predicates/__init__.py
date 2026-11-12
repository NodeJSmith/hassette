"""Predicates combine accessors and conditions to form reusable boolean functions.

A predicate takes a ``source`` callable that extracts a value from an event, and a ``condition`` that
tests the extracted value. The condition may be a literal value, a callable, or a more complex condition object.
Conditions can be composed of other conditions to form complex logic.

Examples:
    Basic value comparison

    ```python
    ValueIs(source=get_entity_id, condition="light.kitchen")
    ```

    With a callable condition

    ```python
    def is_kitchen_light(entity_id: str) -> bool:
        return entity_id == "light.kitchen"

    ValueIs(source=get_entity_id, condition=is_kitchen_light)
    ```

    With a condition object

    ```python
    ValueIs(
        source=get_entity_id,
        condition=C.IsIn(collection=["light.kitchen", "light.living"]),
    )
    ```

    Combining multiple predicates

    ```python
    P.AllOf(predicates=[
        P.DomainMatches("light"),
        P.EntityMatches("light.kitchen"),
        P.StateTo("on"),
    ])
    ```
"""

from .combinators import AllOf, AnyOf, Guard, Not, summarize_top_level
from .comparison import compare_value, normalize_where
from .event_matching import DomainMatches, EntityMatches, ServiceDataWhere, ServiceMatches
from .state import (
    AttrComparison,
    AttrDidChange,
    AttrFrom,
    AttrTo,
    DidChange,
    EventEntityFresh,
    IsMissing,
    IsPresent,
    StateComparison,
    StateDidChange,
    StateFrom,
    StateTo,
    ValueIs,
)

__all__ = [
    "AllOf",
    "AnyOf",
    "AttrComparison",
    "AttrDidChange",
    "AttrFrom",
    "AttrTo",
    "DidChange",
    "DomainMatches",
    "EntityMatches",
    "EventEntityFresh",
    "Guard",
    "IsMissing",
    "IsPresent",
    "Not",
    "ServiceDataWhere",
    "ServiceMatches",
    "StateComparison",
    "StateDidChange",
    "StateFrom",
    "StateTo",
    "ValueIs",
    "compare_value",
    "normalize_where",
    "summarize_top_level",
]

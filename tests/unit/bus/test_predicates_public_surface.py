"""Pin the public names exposed by ``hassette.event_handling.predicates`` (imported by users as ``P``)."""

import inspect

from hassette.event_handling import predicates as P

EXPECTED_PUBLIC_NAMES = frozenset(
    {
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
    }
)


def test_predicates_exposes_expected_public_names() -> None:
    """Every public class or function defined under the predicates namespace is exactly the pinned set."""
    defined_here = {
        name
        for name, obj in vars(P).items()
        if not name.startswith("_")
        and (inspect.isclass(obj) or inspect.isfunction(obj))
        and obj.__module__.startswith(P.__name__)
    }
    assert defined_here == EXPECTED_PUBLIC_NAMES

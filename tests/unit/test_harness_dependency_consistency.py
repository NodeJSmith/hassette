"""Unit test: harness _DEPENDENCIES entries stay in sync with real service depends_on.

Tests:
- Topological sort function (unit tests for the string-based implementation)
- Bidirectional validation: harness _DEPENDENCIES ⊆ real depends_on and vice versa
- Structural: _starters.keys() == set(_COMPONENT_CLASS_MAP.keys()) | harness_only_components
"""

import pytest

from hassette.test_utils.harness import (
    _COMPONENT_CLASS_MAP,
    _DEPENDENCIES,
    HassetteHarness,
    topological_sort,
)

_starters = HassetteHarness._starters

_REVERSE_CLASS_MAP: dict[type, str] = {v: k for k, v in _COMPONENT_CLASS_MAP.items()}


# ---------------------------------------------------------------------------
# Topological sort unit tests
# ---------------------------------------------------------------------------


def test_topological_sort_empty() -> None:
    """Empty graph returns empty list."""
    assert topological_sort({}) == []


def test_topological_sort_linear() -> None:
    """Linear chain: a → b → c returns [a, b, c] order (deps before dependents)."""
    graph: dict[str, set[str]] = {
        "a": set(),
        "b": {"a"},
        "c": {"b"},
    }
    result = topological_sort(graph)
    assert result.index("a") < result.index("b") < result.index("c")


def test_topological_sort_diamond() -> None:
    """Diamond: d depends on b and c, both depend on a."""
    graph: dict[str, set[str]] = {
        "a": set(),
        "b": {"a"},
        "c": {"a"},
        "d": {"b", "c"},
    }
    result = topological_sort(graph)
    assert result.index("a") < result.index("b")
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("d")
    assert result.index("c") < result.index("d")


def test_topological_sort_cycle_raises() -> None:
    """Cycle in graph raises ValueError."""
    graph: dict[str, set[str]] = {
        "a": {"b"},
        "b": {"a"},
    }
    with pytest.raises(ValueError, match=r"[Cc]ycle"):
        topological_sort(graph)


# ---------------------------------------------------------------------------
# Bidirectional dependency consistency tests
# ---------------------------------------------------------------------------


def test_harness_dependencies_subset_of_real() -> None:
    """Validates harness _DEPENDENCIES ⊆ real depends_on."""
    for component_name, harness_deps in _DEPENDENCIES.items():
        real_class = _COMPONENT_CLASS_MAP.get(component_name)
        if real_class is None:
            continue

        real_dep_types = set(real_class.depends_on)

        for dep_name in harness_deps:
            dep_class = _COMPONENT_CLASS_MAP.get(dep_name)
            assert dep_class is not None, (
                f"Harness _DEPENDENCIES[{component_name!r}] references {dep_name!r}, "
                f"but {dep_name!r} has no entry in _COMPONENT_CLASS_MAP. "
                f"Either add the mapping or update _DEPENDENCIES."
            )

            match_found = any(issubclass(dep_class, real_dep_type) for real_dep_type in real_dep_types)
            assert match_found, (
                f"Harness declares {component_name!r} depends on {dep_name!r} ({dep_class.__name__}), "
                f"but {real_class.__name__}.depends_on={[t.__name__ for t in real_class.depends_on]} "
                f"contains no matching type.  Update either _DEPENDENCIES in harness.py or the "
                f"real service's depends_on ClassVar."
            )


def test_real_dependencies_subset_of_harness() -> None:
    """Validates real depends_on ⊆ harness _DEPENDENCIES (for mapped components)."""
    for component_name, real_class in _COMPONENT_CLASS_MAP.items():
        harness_deps = _DEPENDENCIES.get(component_name, set())

        for dep_type in real_class.depends_on:
            dep_name = _REVERSE_CLASS_MAP.get(dep_type)
            if dep_name is None:
                continue

            assert dep_name in harness_deps, (
                f"{real_class.__name__}.depends_on includes {dep_type.__name__} "
                f"(harness name: {dep_name!r}), but _DEPENDENCIES[{component_name!r}] "
                f"= {harness_deps} does not include it. Update _DEPENDENCIES in harness.py."
            )


# ---------------------------------------------------------------------------
# Structural test: _starters keys match _COMPONENT_CLASS_MAP + harness-only
# ---------------------------------------------------------------------------


def test_starters_match_component_map() -> None:
    """_starters.keys() must equal _COMPONENT_CLASS_MAP.keys() | harness_only_components.

    harness_only_components are components with starters that have no real service class
    counterpart (e.g. mock servers, registries, or harness-specific helpers).
    """
    harness_only_components = {"api_mock", "file_watcher", "state_registry"}

    expected = set(_COMPONENT_CLASS_MAP.keys()) | harness_only_components
    actual = set(_starters.keys())

    assert actual == expected, (
        f"_starters keys do not match expected set.\n"
        f"  Extra in _starters (ghost starters):  {actual - expected}\n"
        f"  Missing from _starters (no starter):  {expected - actual}"
    )

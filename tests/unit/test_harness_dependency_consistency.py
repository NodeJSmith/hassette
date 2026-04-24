"""Unit test: harness _DEPENDENCIES entries stay in sync with real service depends_on.

Bidirectional validation:
- Forward (harness ⊆ real): every harness dep maps to a real depends_on entry.
- Reverse (real ⊆ harness): every real depends_on type that has a harness mapping
  appears in the harness's _DEPENDENCIES for that component.
"""

from hassette.test_utils.harness import _COMPONENT_CLASS_MAP, _DEPENDENCIES

_REVERSE_CLASS_MAP: dict[type, str] = {v: k for k, v in _COMPONENT_CLASS_MAP.items()}


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

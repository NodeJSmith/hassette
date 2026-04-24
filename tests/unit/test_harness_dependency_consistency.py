"""Unit test: harness _DEPENDENCIES entries stay in sync with real service depends_on.

This test is one-directional by design: it validates that every dependency declared in the
harness's ``_DEPENDENCIES`` dict is also present in the real service class's ``depends_on``
ClassVar.  The real service may declare additional dependencies not present in the harness
(the harness is intentionally coarser), so the inverse direction is not checked.
"""

from hassette.test_utils.harness import _COMPONENT_CLASS_MAP, _DEPENDENCIES


def test_harness_dependencies_match_real_depends_on() -> None:
    """For each harness component in _COMPONENT_CLASS_MAP, every declared harness dep
    maps to a type that appears in the real service class's depends_on list.

    Validates harness _DEPENDENCIES ⊆ real depends_on (one-directional).
    """
    for component_name, harness_deps in _DEPENDENCIES.items():
        real_class = _COMPONENT_CLASS_MAP.get(component_name)
        if real_class is None:
            # Component has no real-class mapping (api_mock, file_watcher, state_registry)
            # — consistency check skipped for this entry.
            continue

        real_dep_types = set(real_class.depends_on)

        for dep_name in harness_deps:
            dep_class = _COMPONENT_CLASS_MAP.get(dep_name)
            assert dep_class is not None, (
                f"Harness _DEPENDENCIES[{component_name!r}] references {dep_name!r}, "
                f"but {dep_name!r} has no entry in _COMPONENT_CLASS_MAP. "
                f"Either add the mapping or update _DEPENDENCIES."
            )

            # The real dep class (or a subclass of it) must appear in the real service's depends_on.
            match_found = any(issubclass(dep_class, real_dep_type) for real_dep_type in real_dep_types)
            assert match_found, (
                f"Harness declares {component_name!r} depends on {dep_name!r} ({dep_class.__name__}), "
                f"but {real_class.__name__}.depends_on={[t.__name__ for t in real_class.depends_on]} "
                f"contains no matching type.  Update either _DEPENDENCIES in harness.py or the "
                f"real service's depends_on ClassVar."
            )

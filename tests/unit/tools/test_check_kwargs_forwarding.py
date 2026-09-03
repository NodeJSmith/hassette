"""Characterization tests for tools/check_kwargs_forwarding.py.

These pin the guard's observable behavior — which blind '**kwargs: object/Any' forwards into
a constructor call are flagged — so the detection internals can be reworked without changing
what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_kwargs_forwarding import check_file, iter_paths

#: Every .py file under src/hassette, captured once so the not-empty guard and the
#: parametrization below see the same collection.
REPO_FILES = iter_paths()

# Each case: (id, source, expected violations as [(lineno, message), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "object_forwarded_into_constructor_flagged",
        """\
        def make_spec(**overrides: object) -> RestartSpec:
            return RestartSpec(**overrides)
        """,
        [(2, "make_spec: '**overrides: object' forwarded blindly via '**overrides' into RestartSpec(...)")],
    ),
    (
        "any_forwarded_into_constructor_flagged",
        """\
        def make_spec(**overrides: Any) -> RestartSpec:
            return RestartSpec(**overrides)
        """,
        [(2, "make_spec: '**overrides: Any' forwarded blindly via '**overrides' into RestartSpec(...)")],
    ),
    (
        "typing_any_qualified_flagged",
        """\
        import typing

        def make_spec(**overrides: typing.Any) -> RestartSpec:
            return RestartSpec(**overrides)
        """,
        [(4, "make_spec: '**overrides: Any' forwarded blindly via '**overrides' into RestartSpec(...)")],
    ),
    (
        "method_flagged_with_qualname",
        """\
        class SpecFactory:
            def build(self, **overrides: object) -> RestartSpec:
                return RestartSpec(**overrides)
        """,
        [(3, "SpecFactory.build: '**overrides: object' forwarded blindly via '**overrides' into RestartSpec(...)")],
    ),
    (
        "nested_closure_flagged_with_qualname",
        """\
        def make_factory():
            def factory(**overrides: object) -> RestartSpec:
                return RestartSpec(**overrides)
            return factory
        """,
        [(3, "make_factory.factory: '**overrides: object' forwarded blindly via '**overrides' into RestartSpec(...)")],
    ),
    (
        "lowercase_target_not_flagged",
        """\
        def wrapper(*args: object, **kwargs: Any) -> Any:
            return original(*args, **kwargs)
        """,
        [],
    ),
    (
        "shadowed_kwarg_in_nested_function_not_misattributed_to_outer",
        """\
        def outer(**kwargs: object) -> RestartSpec:
            def inner(**kwargs: int) -> Foo:
                return Foo(**kwargs)
            return RestartSpec(a=1)
        """,
        [],
    ),
    (
        "nested_function_own_violation_attributed_to_itself_not_outer",
        """\
        def outer(**kwargs: object) -> RestartSpec:
            def inner(**kwargs: object) -> Foo:
                return Foo(**kwargs)
            return RestartSpec(a=1)
        """,
        [(3, "outer.inner: '**kwargs: object' forwarded blindly via '**kwargs' into Foo(...)")],
    ),
    (
        "closure_over_outer_kwargs_flagged_not_missed",
        """\
        def outer(**kwargs: object) -> Callable[[], Foo]:
            def inner() -> Foo:
                return Foo(**kwargs)
            return inner
        """,
        [(3, "outer: '**kwargs: object' forwarded blindly via '**kwargs' into Foo(...)")],
    ),
    (
        "local_reassignment_in_closure_not_misattributed_to_outer",
        """\
        def outer(**kwargs: object) -> RestartSpec:
            def inner() -> Foo:
                kwargs = {"a": 1}
                return Foo(**kwargs)
            return RestartSpec(**kwargs)
        """,
        [(5, "outer: '**kwargs: object' forwarded blindly via '**kwargs' into RestartSpec(...)")],
    ),
    (
        "nonlocal_reassignment_in_closure_still_flagged",
        """\
        def outer(**kwargs: object) -> Foo:
            def inner() -> Foo:
                nonlocal kwargs
                kwargs = {"a": 1}
                return Foo(**kwargs)
            return inner()
        """,
        [(5, "outer: '**kwargs: object' forwarded blindly via '**kwargs' into Foo(...)")],
    ),
    (
        "self_recursive_super_call_not_flagged",
        """\
        class Base:
            def __init_subclass__(cls, **kwargs: Any) -> None:
                super().__init_subclass__(**kwargs)
        """,
        [],
    ),
    (
        "dynamically_referenced_class_in_lowercase_var_not_flagged",
        """\
        def add_child(self, child_class, **kwargs: Any):
            return child_class(**kwargs)
        """,
        [],
    ),
    (
        "typed_kwarg_not_flagged",
        """\
        def make_spec(**overrides: int) -> RestartSpec:
            return RestartSpec(**overrides)
        """,
        [],
    ),
    (
        "no_forwarding_not_flagged",
        """\
        def make_spec(**overrides: object) -> RestartSpec:
            defaults = {"backoff_base_seconds": 0}
            defaults.update(overrides)
            return RestartSpec(**defaults)
        """,
        [],
    ),
    (
        "no_kwargs_param_not_flagged",
        """\
        def make_spec(overrides: dict[str, object]) -> RestartSpec:
            return RestartSpec(**overrides)
        """,
        [],
    ),
    (
        "escape_hatch_annotation_suppresses",
        """\
        def factory(**kwargs: Any) -> Task:
            return Task(**kwargs)  # kwargs-forward-ok: asyncio calling convention
        """,
        [],
    ),
    (
        "escape_hatch_requires_reason",
        """\
        def factory(**kwargs: Any) -> Task:
            return Task(**kwargs)  # kwargs-forward-ok:
        """,
        [(2, "factory: '**kwargs: Any' forwarded blindly via '**kwargs' into Task(...)")],
    ),
    (
        "subscript_mutation_of_captured_kwargs_still_flagged",
        """\
        def outer(**kwargs: object) -> Foo:
            def inner() -> Foo:
                kwargs["a"] = 1
                return Foo(**kwargs)
            return inner()
        """,
        [(4, "outer: '**kwargs: object' forwarded blindly via '**kwargs' into Foo(...)")],
    ),
    (
        "attribute_mutation_of_captured_kwargs_still_flagged",
        """\
        def outer(**kwargs: object) -> Foo:
            def inner() -> Foo:
                kwargs.extra = 1
                return Foo(**kwargs)
            return inner()
        """,
        [(4, "outer: '**kwargs: object' forwarded blindly via '**kwargs' into Foo(...)")],
    ),
    (
        "subscripted_generic_constructor_flagged",
        """\
        def make_model(**overrides: object) -> Model[int]:
            return Model[int](**overrides)
        """,
        [(2, "make_model: '**overrides: object' forwarded blindly via '**overrides' into Model(...)")],
    ),
    (
        "subscripted_screaming_case_registry_not_flagged",
        """\
        def dispatch(**overrides: object) -> str:
            return HANDLERS[key](**overrides)
        """,
        [],
    ),
    (
        "subscripted_screaming_case_registry_with_dotted_key_not_flagged",
        """\
        def dispatch(**overrides: object) -> str:
            return CLI_FORMATTERS[meta.style](**overrides)
        """,
        [],
    ),
    (
        "subscripted_acronym_class_not_flagged_known_false_negative",
        """\
        def make_url(**overrides: object) -> URL[int]:
            return URL[int](**overrides)
        """,
        [],
    ),
    (
        "shadowing_definition_time_default_not_flagged_known_false_negative",
        """\
        def outer(**kwargs: object) -> Callable[..., None]:
            def inner(x=Foo(**kwargs), **kwargs: int) -> None:
                pass
            return inner
        """,
        [],
    ),
    (
        "nested_class_method_capture_not_flagged_known_false_negative",
        """\
        def outer(**kwargs: object) -> type:
            class Local:
                def method(self) -> Foo:
                    return Foo(**kwargs)
            return Local
        """,
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected


def test_repo_files_found() -> None:
    """Guard against a misconfigured SCAN_DIRS silently yielding zero files to check."""
    assert REPO_FILES


@pytest.mark.parametrize("path", REPO_FILES, ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual src/hassette source it polices."""
    assert check_file(path) == []

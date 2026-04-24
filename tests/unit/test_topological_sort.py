"""Unit tests for topological_sort() in hassette.utils.service_utils."""

from typing import ClassVar

import pytest

from hassette.utils import topological_sort

# ---------------------------------------------------------------------------
# Stub Resource subclasses
# ---------------------------------------------------------------------------
# These are plain classes that satisfy the `getattr(node, 'depends_on', [])`
# contract. They do NOT subclass the real Resource (which requires a live
# Hassette instance), keeping these tests fully synchronous and dependency-free.
# ---------------------------------------------------------------------------


class StubBase:
    """Minimal stub base so stubs share a common ancestor for isinstance checks."""


class A(StubBase):
    depends_on: ClassVar[list] = []


class B(StubBase):
    depends_on: ClassVar[list] = [A]


class C(StubBase):
    depends_on: ClassVar[list] = [A]


class D(StubBase):
    depends_on: ClassVar[list] = [B, C]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_list():
    """Empty input returns empty output."""
    result = topological_sort([])
    assert result == []


def test_single_node_no_deps():
    """Single node with no deps is returned as-is."""
    result = topological_sort([A])
    assert result == [A]


def test_linear_chain():
    """A → B → C: C has no deps, A depends on B which depends on C.
    Expected init order: C before B before A."""

    class Root(StubBase):
        depends_on: ClassVar[list] = []

    class Mid(StubBase):
        depends_on: ClassVar[list] = [Root]

    class Leaf(StubBase):
        depends_on: ClassVar[list] = [Mid]

    result = topological_sort([Leaf, Mid, Root])
    # Root must come before Mid, Mid before Leaf
    assert result.index(Root) < result.index(Mid)
    assert result.index(Mid) < result.index(Leaf)
    # All three must be present
    assert len(result) == 3


def test_diamond():
    """Diamond: D depends on B and C, both depend on A.
    Expected: A before B and C, B and C before D."""
    result = topological_sort([A, B, C, D])
    assert A in result
    assert B in result
    assert C in result
    assert D in result
    # Deduplication: each appears exactly once
    assert len(result) == 4
    # Order constraints
    assert result.index(A) < result.index(B)
    assert result.index(A) < result.index(C)
    assert result.index(B) < result.index(D)
    assert result.index(C) < result.index(D)


def test_cycle_raises():
    """A → B → A (mutual cycle) must raise ValueError with both names."""

    class CycleA(StubBase):
        pass  # depends_on set after both classes defined

    class CycleB(StubBase):
        pass

    CycleA.depends_on = [CycleB]
    CycleB.depends_on = [CycleA]

    with pytest.raises(ValueError, match=r"Cycle detected:.*CycleA.*CycleB|Cycle detected:.*CycleB.*CycleA"):
        topological_sort([CycleA, CycleB])


def test_self_dependency_raises():
    """A → A (self-dep) must raise ValueError."""

    class SelfDep(StubBase):
        pass

    SelfDep.depends_on = [SelfDep]

    with pytest.raises(ValueError, match="SelfDep"):
        topological_sort([SelfDep])


def test_disconnected_components():
    """Nodes with no deps (disconnected from others) are all included in output."""

    class Isolated1(StubBase):
        depends_on: ClassVar[list] = []

    class Isolated2(StubBase):
        depends_on: ClassVar[list] = []

    class Isolated3(StubBase):
        depends_on: ClassVar[list] = []

    result = topological_sort([Isolated1, Isolated2, Isolated3])
    assert set(result) == {Isolated1, Isolated2, Isolated3}
    assert len(result) == 3


def test_disconnected_with_dep_chain():
    """Mix of connected and disconnected components — all appear in output."""

    class Standalone(StubBase):
        depends_on: ClassVar[list] = []

    class Root(StubBase):
        depends_on: ClassVar[list] = []

    class Dependent(StubBase):
        depends_on: ClassVar[list] = [Root]

    result = topological_sort([Standalone, Dependent, Root])
    assert set(result) == {Standalone, Dependent, Root}
    assert result.index(Root) < result.index(Dependent)


def test_stable_ordering():
    """Nodes at the same depth (no ordering constraint between them) appear
    in the same relative order as the input list."""

    class R1(StubBase):
        depends_on: ClassVar[list] = []

    class R2(StubBase):
        depends_on: ClassVar[list] = []

    class R3(StubBase):
        depends_on: ClassVar[list] = []

    class R4(StubBase):
        depends_on: ClassVar[list] = []

    # All four are roots — no deps between them.
    # They should appear in input order: R1, R2, R3, R4
    result = topological_sort([R1, R2, R3, R4])
    assert result == [R1, R2, R3, R4]

    # Different input order → different (but still stable) output
    result2 = topological_sort([R3, R1, R4, R2])
    assert result2 == [R3, R1, R4, R2]


def test_deps_not_in_input_are_excluded():
    """Dependencies not in the input list are NOT auto-included in the output.
    The function only sorts what it is given."""

    class External(StubBase):
        depends_on: ClassVar[list] = []

    class GivenNode(StubBase):
        depends_on: ClassVar[list] = [External]

    # External is NOT in the input list
    result = topological_sort([GivenNode])
    assert result == [GivenNode]
    assert External not in result


def test_cycle_error_message_format():
    """ValueError message must start with 'Cycle detected:' and contain → separators."""

    class X(StubBase):
        pass

    class Y(StubBase):
        pass

    X.depends_on = [Y]
    Y.depends_on = [X]

    with pytest.raises(ValueError, match=r"Cycle detected:.*→"):
        topological_sort([X, Y])

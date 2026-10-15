import pickle

import pytest

from hassette import const
from hassette.const import ANY_VALUE, MISSING_VALUE, NOT_PROVIDED, FalseySentinel

SENTINEL_NAMES = ["MISSING_VALUE", "NOT_PROVIDED", "ANY_VALUE"]


@pytest.mark.parametrize("name", SENTINEL_NAMES)
def test_constant_is_enum_member(name: str) -> None:
    sentinel = getattr(const, name)
    assert sentinel is FalseySentinel[name]
    assert isinstance(sentinel, FalseySentinel)


@pytest.mark.parametrize("name", SENTINEL_NAMES)
def test_sentinel_is_falsey(name: str) -> None:
    sentinel = getattr(const, name)
    assert not sentinel
    assert bool(sentinel) is False


@pytest.mark.parametrize("name", SENTINEL_NAMES)
def test_sentinel_repr_and_str(name: str) -> None:
    sentinel = getattr(const, name)
    assert repr(sentinel) == f"<{name}>"
    assert str(sentinel) == f"<{name}>"
    assert f"{sentinel}" == f"<{name}>"


@pytest.mark.parametrize("name", SENTINEL_NAMES)
def test_sentinel_pickle_round_trip_preserves_identity(name: str) -> None:
    sentinel = getattr(const, name)
    assert pickle.loads(pickle.dumps(sentinel)) is sentinel  # noqa: S301 - round-trips trusted local data


def test_sentinels_are_distinct() -> None:
    assert len({MISSING_VALUE, NOT_PROVIDED, ANY_VALUE}) == 3

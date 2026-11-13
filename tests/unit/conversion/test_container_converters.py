"""Tests that container converters reject values whose iteration would not yield the intended items."""

from typing import Any

import pytest

from hassette.conversion import ANNOTATION_CONVERTER
from hassette.exceptions import UnableToConvertValueError


@pytest.mark.parametrize(
    ("value", "annotation"),
    [
        pytest.param("abc", list[str], id="str_to_list"),
        pytest.param(b"abc", list[int], id="bytes_to_list"),
        pytest.param("abc", set[str], id="str_to_set"),
        pytest.param({"a": 1, "b": 2}, list[str], id="dict_to_list"),
        pytest.param(["ab", "cd"], dict[str, str], id="list_of_pairs_to_dict"),
        pytest.param([("a", 1)], dict[str, int], id="list_of_tuples_to_dict"),
    ],
)
def test_container_converter_rejects_non_container_value(value: Any, annotation: Any):
    """Strings, mappings for sequence types, and pair sequences for dicts raise instead of being exploded."""
    with pytest.raises(UnableToConvertValueError):
        ANNOTATION_CONVERTER.convert(value, annotation)


@pytest.mark.parametrize(
    ("value", "annotation", "expected"),
    [
        pytest.param((1, 2), list[int], [1, 2], id="tuple_to_list"),
        pytest.param([1, 1, 2], set[int], {1, 2}, id="list_to_set"),
        pytest.param({"1", "2"}, frozenset[int], frozenset({1, 2}), id="set_to_frozenset"),
        pytest.param({"a": "1"}, dict[str, int], {"a": 1}, id="dict_converts_values"),
    ],
)
def test_container_converter_still_coerces_between_containers(value: Any, annotation: Any, expected: Any):
    """Coercion between list, set, tuple and frozenset, and dict value conversion, keep working."""
    assert ANNOTATION_CONVERTER.convert(value, annotation) == expected

"""Tests for _ResourceContextFilter deduplication on shared loggers.

Verifies:
- __eq__/__hash__ prevent filter accumulation across repeated Resource constructions
  sharing a logger name (the hot-reload scenario).
- Filters with different source_tier values are not collapsed.
"""

from logging import getLogger

from hassette.resources.base import _ResourceContextFilter
from tests.support.mock_hassette import make_mock_hassette

from .conftest import ConcreteResource


class TestResourceContextFilterEquality:
    """Value-based equality so stdlib Filterer.addFilter deduplicates correctly."""

    def test_same_source_tier_are_equal(self) -> None:
        a = _ResourceContextFilter("framework")
        b = _ResourceContextFilter("framework")

        assert a == b
        assert hash(a) == hash(b)

    def test_different_source_tier_are_not_equal(self) -> None:
        a = _ResourceContextFilter("framework")
        b = _ResourceContextFilter("app")

        assert a != b

    def test_not_equal_to_other_types(self) -> None:
        f = _ResourceContextFilter("framework")

        assert f != "framework"
        assert f != 42


class TestFilterAccumulation:
    """Repeated Resource construction must not pile up duplicate filters."""

    def test_shared_logger_gets_one_filter(self) -> None:
        """Simulates hot-reload: two resources with the same parent derive the same logger name."""
        hassette = make_mock_hassette(sealed=False)
        parent = ConcreteResource(hassette=hassette)

        r1 = ConcreteResource(hassette=hassette, parent=parent)
        logger_name = r1.logger.name

        r2 = ConcreteResource(hassette=hassette, parent=parent)
        assert r2.logger.name == logger_name, "precondition: both share a logger name"

        logger = getLogger(logger_name)
        context_filters = [f for f in logger.filters if isinstance(f, _ResourceContextFilter)]

        assert len(context_filters) == 1

"""Unit tests for TelemetryQueryService module-level SQL helper functions."""

from hassette.core.telemetry_query_service import _since_clause


class TestSinceClause:
    """Tests for the _since_clause() helper."""

    def test_none_returns_empty(self) -> None:
        """When since is None, returns empty string and empty dict."""
        fragment, params = _since_clause(None, "hi.execution_start_ts")
        assert fragment == ""
        assert params == {}

    def test_float_returns_parameterized_fragment(self) -> None:
        """When since is a float, returns AND clause and bind param."""
        fragment, params = _since_clause(1_700_000_000.0, "hi.execution_start_ts")
        assert "hi.execution_start_ts" in fragment
        assert ">= :since" in fragment
        assert params == {"since": 1_700_000_000.0}

    def test_fragment_starts_with_and(self) -> None:
        """Fragment starts with AND when since is provided."""
        fragment, _ = _since_clause(0.0, "je.execution_start_ts")
        assert fragment.strip().startswith("AND")

    def test_zero_since_is_valid(self) -> None:
        """since=0.0 (epoch origin) is valid and produces a filter."""
        fragment, params = _since_clause(0.0, "col")
        assert fragment != ""
        assert params == {"since": 0.0}

    def test_different_column_names(self) -> None:
        """Column name is correctly embedded in the fragment."""
        fragment_hi, _ = _since_clause(1.0, "hi.execution_start_ts")
        fragment_je, _ = _since_clause(1.0, "je.execution_start_ts")
        assert "hi.execution_start_ts" in fragment_hi
        assert "je.execution_start_ts" in fragment_je

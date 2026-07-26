"""Unit tests for TelemetryQueryService module-level SQL helper functions."""

from hassette.core.telemetry.helpers import handler_job_union_arms, since_clause
from hassette.test_utils.config import TEST_EPOCH_B


class TestSinceClause:
    """Tests for the since_clause() helper."""

    def test_none_returns_empty(self) -> None:
        """When since is None, returns empty string and empty dict."""
        fragment, params = since_clause(None, "hi.execution_start_ts")
        assert fragment == ""
        assert params == {}

    def test_float_returns_parameterized_fragment(self) -> None:
        """When since is a float, returns AND clause and bind param."""
        fragment, params = since_clause(TEST_EPOCH_B, "hi.execution_start_ts")
        assert "hi.execution_start_ts" in fragment
        assert ">= :since" in fragment
        assert params == {"since": TEST_EPOCH_B}

    def test_fragment_starts_with_and(self) -> None:
        """Fragment starts with AND when since is provided."""
        fragment, _ = since_clause(0.0, "je.execution_start_ts")
        assert fragment.strip().startswith("AND")

    def test_zero_since_is_valid(self) -> None:
        """since=0.0 (epoch origin) is valid and produces a filter."""
        fragment, params = since_clause(0.0, "col")
        assert fragment != ""
        assert params == {"since": 0.0}

    def test_different_column_names(self) -> None:
        """Column name is correctly embedded in the fragment."""
        fragment_hi, _ = since_clause(1.0, "hi.execution_start_ts")
        fragment_je, _ = since_clause(1.0, "je.execution_start_ts")
        assert "hi.execution_start_ts" in fragment_hi
        assert "je.execution_start_ts" in fragment_je


class TestHandlerJobUnionArms:
    """Tests for the handler_job_union_arms() helper."""

    def test_both_arms_present(self) -> None:
        """Fragment contains both the handler and job SELECT arms joined by UNION ALL."""
        fragment, _ = handler_job_union_arms("SELECT l.app_key", "SELECT sj.app_key")
        assert "SELECT l.app_key" in fragment
        assert "SELECT sj.app_key" in fragment
        assert "UNION ALL" in fragment
        assert "FROM executions e_h" in fragment
        assert "JOIN listeners l ON l.id = e_h.listener_id" in fragment
        assert "WHERE e_h.kind = 'handler'" in fragment
        assert "FROM executions e_j" in fragment
        assert "JOIN scheduled_jobs sj ON sj.id = e_j.job_id" in fragment
        assert "WHERE e_j.kind = 'job'" in fragment

    def test_extra_where_included_per_arm(self) -> None:
        """extra_handler_where / extra_job_where are appended to their respective arms only."""
        fragment, _ = handler_job_union_arms(
            "SELECT 1",
            "SELECT 1",
            extra_handler_where="AND l.app_key = :app_key",
            extra_job_where="AND sj.app_key = :app_key",
        )
        handler_arm, job_arm = fragment.split("UNION ALL")
        assert "AND l.app_key = :app_key" in handler_arm
        assert "AND sj.app_key = :app_key" not in handler_arm
        assert "AND sj.app_key = :app_key" in job_arm

    def test_since_param_deduplicated(self) -> None:
        """Both arms bind :since, but the merged params dict has a single entry."""
        fragment, params = handler_job_union_arms("SELECT 1", "SELECT 1", since=TEST_EPOCH_B)
        assert fragment.count(":since") == 2
        assert params == {"since": TEST_EPOCH_B, "source_tier": "app"}

    def test_since_none_omits_since_param(self) -> None:
        """since=None means no since_clause filter and no :since param."""
        fragment, params = handler_job_union_arms("SELECT 1", "SELECT 1", since=None)
        assert ":since" not in fragment
        assert "since" not in params

    def test_source_tier_all_omits_param(self) -> None:
        """source_tier='all' skips the source_tier filter entirely."""
        fragment, params = handler_job_union_arms("SELECT 1", "SELECT 1", source_tier="all")
        assert ":source_tier" not in fragment
        assert params == {}

    def test_instance_index_adds_clause_and_param(self) -> None:
        """instance_index adds a per-arm instance filter and a single bind param."""
        fragment, params = handler_job_union_arms("SELECT 1", "SELECT 1", instance_index=2, source_tier="all")
        assert "AND l.instance_index = :instance_index" in fragment
        assert "AND sj.instance_index = :instance_index" in fragment
        assert params == {"instance_index": 2}

    def test_instance_index_none_omits_clause(self) -> None:
        """instance_index=None (default) adds no instance filter or param."""
        fragment, params = handler_job_union_arms("SELECT 1", "SELECT 1", source_tier="all")
        assert "instance_index" not in fragment
        assert params == {}

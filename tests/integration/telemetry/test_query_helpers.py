"""Integration tests for telemetry query helper functions and source_tier scoping behavior."""

from hassette.core.telemetry.helpers import source_tier_clause
from hassette.core.telemetry.query_service import TelemetryQueryService

from .helpers import DbFixture, insert_execution, insert_invocation, insert_job, insert_listener


class TestSourceTierClause:
    def test_any_alias_accepted(self) -> None:
        """source_tier_clause accepts any alias (developer-controlled, not user input)."""
        fragment, params = source_tier_clause("app", "custom_alias")
        assert "custom_alias.source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_framework_tier_returns_filter_fragment(self) -> None:
        """source_tier_clause('framework', ...) returns an AND clause with 'framework' param."""
        fragment, params = source_tier_clause("framework", "l")
        assert "source_tier" in fragment
        assert params == {"source_tier": "framework"}

    def test_all_tier_returns_empty(self) -> None:
        """source_tier_clause('all', ...) returns an empty fragment and empty params."""
        fragment, params = source_tier_clause("all", "hi")
        assert fragment == ""
        assert params == {}

    def test_app_tier_returns_filter_fragment(self) -> None:
        """source_tier_clause('app', ...) returns an AND clause with 'app' param."""
        fragment, params = source_tier_clause("app", "je")
        assert "source_tier" in fragment
        assert params == {"source_tier": "app"}

    def test_all_valid_aliases_accepted(self) -> None:
        """All four valid aliases are accepted without raising."""
        for alias in ("l", "hi", "je", "sj"):
            # Should not raise
            source_tier_clause("app", alias)


class TestGetAllAppSummariesFrameworkTier:
    async def test_get_all_app_summaries_framework_tier(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """source_tier='framework' selects active_framework_listeners and active_framework_scheduled_jobs."""
        db_svc, session_id = db

        # Framework-tier listener and job under __hassette__
        fw_listener = await insert_listener(
            db_svc, app_key="__hassette__", handler_method="on_fw", source_tier="framework"
        )
        fw_job = await insert_job(db_svc, app_key="__hassette__", job_name="fw_job", source_tier="framework")

        # App-tier listener and job (should NOT appear for framework query)
        _app_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")
        _app_job = await insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")

        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )
        await insert_execution(db_svc, fw_job, session_id, status="success", duration_ms=10.0, source_tier="framework")

        result = await query_service.get_all_app_summaries(source_tier="framework")

        # __hassette__ has framework-tier registrations and activity, so it appears in the result
        assert "__hassette__" in result
        summary = result["__hassette__"]
        assert summary.handler_count == 1
        assert summary.job_count == 1
        assert summary.total_invocations == 1
        assert summary.total_executions == 1

        # my_app's registrations and activity are all app-tier, so it has no framework-tier data
        assert "my_app" not in result

    async def test_get_all_app_summaries_framework_tier_non_hassette_app_key(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """source_tier='framework' shows framework-tier records for non-__hassette__ app_key."""
        db_svc, session_id = db

        # A regular app with mixed-tier listeners
        fw_listener = await insert_listener(db_svc, app_key="my_app", handler_method="on_fw", source_tier="framework")
        await insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")

        await insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )

        result = await query_service.get_all_app_summaries(source_tier="framework")
        # my_app has 1 framework-tier listener (instance 0)
        assert "my_app" in result
        summary = result["my_app"]
        assert summary.handler_count == 1  # only the framework listener
        assert summary.total_invocations == 1

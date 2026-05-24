"""Integration tests for timed_out status in telemetry queries.

Verifies that 'timed_out' is counted as a separate bucket in summaries
and treated as a failure subtype in error-rate calculations.
"""

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_query_service import TelemetryQueryService

from .helpers import (
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
)


class TestListenerSummaryTimedOut:
    async def test_listener_summary_counts_timed_out(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is a separate bucket in ListenerSummary."""
        db_svc, session_id = db
        lid = await insert_listener(db_svc)
        await insert_invocation(db_svc, lid, session_id, status="success")
        await insert_invocation(db_svc, lid, session_id, status="error")
        await insert_invocation(db_svc, lid, session_id, status="timed_out")
        await insert_invocation(db_svc, lid, session_id, status="timed_out")

        summaries = await query_service.get_listener_summary("test_app", 0)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.total_invocations == 4
        assert s.successful == 1
        assert s.failed == 1
        assert s.timed_out == 2
        assert s.cancelled == 0


class TestJobSummaryTimedOut:
    async def test_job_summary_counts_timed_out(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is a separate bucket in JobSummary."""
        db_svc, session_id = db
        jid = await insert_job(db_svc)
        await insert_execution(db_svc, jid, session_id, status="success")
        await insert_execution(db_svc, jid, session_id, status="success")
        await insert_execution(db_svc, jid, session_id, status="error")
        await insert_execution(db_svc, jid, session_id, status="timed_out")

        summaries = await query_service.get_job_summary("test_app", 0)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.total_executions == 4
        assert s.successful == 2
        assert s.failed == 1
        assert s.timed_out == 1

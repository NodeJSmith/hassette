"""Integration tests for POST /api/scheduler/jobs/{job_id}/trigger (manual submission)."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from hassette.exceptions import JobRemovedError
from hassette.scheduler.classes import Job
from hassette.scheduler.triggers import Every
from hassette.test_utils.web_job_helpers import make_real_job

if TYPE_CHECKING:
    from httpx2 import AsyncClient

RECURRING_TRIGGER = Every(seconds=60)
"""Shared recurring-job trigger fixture — most tests here don't care about the interval value."""

TRIGGER_URL = "/api/scheduler/jobs/{job_id}/trigger"


def make_registered_job(  # factory-local: wraps make_real_job for submission-route tests
    *,
    db_id: int = 1,
    name: str = "test_job",
    trigger: object | None = None,
) -> Job:
    """Build a real Job for wiring onto the mock scheduler service's live registry."""
    return make_real_job(name=name, trigger=trigger, db_id=db_id)


class TestTriggerJobEndpoint:
    async def test_returns_202_for_live_job(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST returns 202 and submits through submit_job() for a live registered job."""
        job = make_registered_job(trigger=RECURRING_TRIGGER)
        mock_hassette.scheduler_service.trigger_job = AsyncMock(return_value=job)
        mock_hassette.scheduler_service.submit_job = MagicMock(return_value=None)

        response = await client.post(TRIGGER_URL.format(job_id=1))

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["job_id"] == 1
        assert data["job_name"] == "test_job"
        mock_hassette.scheduler_service.submit_job.assert_called_once_with(job)

    async def test_returns_409_for_unknown_job_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST returns 409 when trigger_job() raises ValueError (job not in the registry)."""
        mock_hassette.scheduler_service.trigger_job = AsyncMock(
            side_effect=ValueError("Job is not currently triggerable")
        )

        response = await client.post(TRIGGER_URL.format(job_id=999))

        assert response.status_code == 409
        assert "not currently triggerable" in response.json()["detail"]

    async def test_returns_409_for_removed_live_handle(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST returns 409 when submit_job() raises JobRemovedError for a stale handle."""
        job = make_registered_job(trigger=RECURRING_TRIGGER)
        mock_hassette.scheduler_service.trigger_job = AsyncMock(return_value=job)
        mock_hassette.scheduler_service.submit_job = MagicMock(side_effect=JobRemovedError(job.name, job.db_id))

        response = await client.post(TRIGGER_URL.format(job_id=1))

        assert response.status_code == 409

    async def test_does_not_dequeue_pending_one_shot(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Manual submission never dequeues or otherwise touches the automatic schedule."""
        job = make_registered_job(trigger=None)
        mock_hassette.scheduler_service.trigger_job = AsyncMock(return_value=job)
        mock_hassette.scheduler_service.submit_job = MagicMock(return_value=None)

        response = await client.post(TRIGGER_URL.format(job_id=1))

        assert response.status_code == 202
        mock_hassette.scheduler_service.dequeue_job.assert_not_called()

    async def test_submits_through_submit_job_regardless_of_guard_state(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Route never preflights guard/single-mode state — submit_job() alone decides the outcome."""
        job = make_registered_job(trigger=RECURRING_TRIGGER)
        job.guard = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        job.guard.is_running.return_value = True
        mock_hassette.scheduler_service.trigger_job = AsyncMock(return_value=job)
        mock_hassette.scheduler_service.submit_job = MagicMock(return_value=None)

        response = await client.post(TRIGGER_URL.format(job_id=1))

        assert response.status_code == 202
        mock_hassette.scheduler_service.submit_job.assert_called_once_with(job)

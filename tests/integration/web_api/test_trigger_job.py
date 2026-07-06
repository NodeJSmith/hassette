"""Integration tests for POST /api/scheduler/jobs/{job_id}/trigger."""

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as date_utils
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import After, Every
from hassette.types.enums import ExecutionMode

if TYPE_CHECKING:
    from httpx2 import AsyncClient


def make_scheduled_job(
    *,
    db_id: int = 1,
    mode: ExecutionMode = ExecutionMode.SINGLE,
    trigger: Any | None = None,
    name: str = "test_job",
) -> ScheduledJob:
    """Build a real ScheduledJob for wiring onto the mock scheduler service's live heap."""
    job = ScheduledJob(
        owner_id="test_owner",
        next_run=date_utils.now(),
        job=lambda: None,
        mode=mode,
        trigger=trigger,
        name=name,
    )
    job.db_id = db_id
    return job


class TestTriggerJobEndpoint:
    async def test_returns_202_for_active_recurring_job(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST returns 202 and dispatches through run_job_with_guard for an active job."""
        job = make_scheduled_job(trigger=Every(seconds=60))
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["job_id"] == 1
        assert data["job_name"] == "test_job"
        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")

    async def test_returns_409_for_unknown_job_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST returns 409 when trigger_now() raises ValueError (job not on the heap)."""
        mock_hassette.scheduler_service.trigger_now = AsyncMock(
            side_effect=ValueError("Job is not currently triggerable")
        )

        response = await client.post("/api/scheduler/jobs/999/trigger")

        assert response.status_code == 409
        assert "not currently triggerable" in response.json()["detail"]

    async def test_returns_409_for_single_mode_guard_held(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST returns 409 for a SINGLE-mode job whose guard reports is_running() True."""
        job = make_scheduled_job(mode=ExecutionMode.SINGLE, trigger=Every(seconds=60))
        job.guard = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        job.guard.is_running.return_value = True
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 409
        assert "currently executing" in response.json()["detail"]
        mock_hassette.scheduler_service.run_job_with_guard.assert_not_called()
        mock_hassette.scheduler_service.dequeue_job.assert_not_called()

    async def test_returns_202_for_restart_mode_guard_held(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST returns 202 for a RESTART-mode job even when the guard reports is_running() True."""
        job = make_scheduled_job(mode=ExecutionMode.RESTART, trigger=Every(seconds=60))
        job.guard = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        job.guard.is_running.return_value = True
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")

    async def test_returns_202_for_queued_mode_guard_held(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST returns 202 for a QUEUED-mode job even when the guard reports is_running() True."""
        job = make_scheduled_job(mode=ExecutionMode.QUEUED, trigger=Every(seconds=60))
        job.guard = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        job.guard.is_running.return_value = True
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")

    async def test_returns_202_for_parallel_mode_regardless_of_guard_state(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST returns 202 for a PARALLEL-mode job — no pre-check applies at all."""
        job = make_scheduled_job(mode=ExecutionMode.PARALLEL, trigger=Every(seconds=60))
        job.guard = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
        job.guard.is_running.return_value = True
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")

    async def test_pending_one_shot_job_is_dequeued_before_dispatch(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST for a still-pending one-shot job (After trigger) dequeues before dispatch."""
        job = make_scheduled_job(trigger=After(seconds=30))
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.dequeue_job.assert_called_once_with(job)
        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")

    async def test_bare_scheduling_with_no_trigger_is_dequeued(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """POST for a job with trigger=None (bare one-shot scheduling) is dequeued before dispatch."""
        job = make_scheduled_job(trigger=None)
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.dequeue_job.assert_called_once_with(job)

    async def test_recurring_job_is_not_dequeued(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST for a recurring job (Every trigger) does not dequeue it from the heap."""
        job = make_scheduled_job(trigger=Every(seconds=60))
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        response = await client.post("/api/scheduler/jobs/1/trigger")

        assert response.status_code == 202
        mock_hassette.scheduler_service.dequeue_job.assert_not_called()

    async def test_dispatches_with_manual_trigger_mode(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """POST spawns run_job_with_guard with trigger_mode='manual' via the task bucket."""
        job = make_scheduled_job(trigger=Every(seconds=60))
        mock_hassette.scheduler_service.trigger_now = AsyncMock(return_value=job)

        await client.post("/api/scheduler/jobs/1/trigger")

        mock_hassette.scheduler_service.run_job_with_guard.assert_called_once_with(job, trigger_mode="manual")
        mock_hassette.scheduler_service.task_bucket.spawn.assert_called_once()

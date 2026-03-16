"""Tests verifying that HTMX partial and API scheduler-job endpoints filter by the correct identity fields."""

from typing import TYPE_CHECKING

import pytest
from whenever import ZonedDateTime

from hassette.scheduler.classes import ScheduledJob
from hassette.test_utils.web_helpers import make_manifest, make_old_snapshot
from hassette.test_utils.web_mocks import create_hassette_stub

if TYPE_CHECKING:
    from httpx import AsyncClient


def _make_job(
    *,
    owner_id: str,
    app_key: str,
    instance_index: int = 0,
    name: str = "test_job",
) -> ScheduledJob:
    """Create a minimal ScheduledJob for filter testing."""
    return ScheduledJob(
        owner_id=owner_id,
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
        app_key=app_key,
        instance_index=instance_index,
        name=name,
    )


# Two apps, each with a different owner_id
JOB_MY_APP = _make_job(owner_id="my_app_0", app_key="my_app", instance_index=0, name="my_app_job_i0")
JOB_MY_APP_I1 = _make_job(owner_id="my_app_1", app_key="my_app", instance_index=1, name="my_app_job_i1")
JOB_OTHER = _make_job(owner_id="other_app_0", app_key="other_app", instance_index=0, name="other_job")
ALL_JOBS = [JOB_MY_APP, JOB_MY_APP_I1, JOB_OTHER]


@pytest.fixture
def mock_hassette():
    """Hassette stub with three scheduler jobs across two apps and two instances."""
    return create_hassette_stub(
        states={},
        manifests=[make_manifest()],
        old_snapshot=make_old_snapshot(),
        scheduler_jobs=list(ALL_JOBS),
    )


class TestSchedulerJobsPartialFiltersByAppKey:
    """GET /partials/scheduler-jobs?app_key=my_app returns only my_app jobs."""

    async def test_filters_by_app_key(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-jobs", params={"app_key": "my_app"})
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i0" in body
        assert "my_app_job_i1" in body
        assert "other_job" not in body

    async def test_returns_all_when_no_app_key(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-jobs")
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i0" in body
        assert "other_job" in body


class TestAppDetailJobsPartialFiltersByAppKey:
    """GET /partials/app-detail-jobs/{app_key} returns only matching app_key jobs."""

    async def test_filters_by_app_key(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-jobs/my_app")
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i0" in body
        assert "other_job" not in body

    async def test_excludes_other_app(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-jobs/other_app")
        assert response.status_code == 200
        body = response.text
        assert "other_job" in body
        assert "my_app_job_i0" not in body


class TestInstanceJobsPartialFiltersByAppKeyAndIndex:
    """GET /partials/instance-jobs/{app_key}/{index} filters by both app_key and instance_index."""

    async def test_filters_by_app_key_and_instance_index_0(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/instance-jobs/my_app/0")
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i0" in body
        # instance 1 job should NOT appear
        assert "my_app_job_i1" not in body
        assert "other_job" not in body

    async def test_filters_by_app_key_and_instance_index_1(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/instance-jobs/my_app/1")
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i1" in body
        assert "my_app_job_i0" not in body
        assert "other_job" not in body

    async def test_empty_for_nonexistent_instance(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/instance-jobs/my_app/99")
        assert response.status_code == 200
        body = response.text
        assert "my_app_job_i0" not in body
        assert "other_job" not in body


class TestApiSchedulerJobsFiltersByAppKey:
    """GET /api/scheduler/jobs?app_key=my_app returns only matching app_key jobs."""

    async def test_filters_by_app_key(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs", params={"app_key": "my_app"})
        assert response.status_code == 200
        data = response.json()
        names = [j["name"] for j in data]
        assert "my_app_job_i0" in names
        assert "my_app_job_i1" in names
        assert "other_job" not in names

    async def test_returns_all_when_no_app_key(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        names = [j["name"] for j in data]
        assert "my_app_job_i0" in names
        assert "other_job" in names

    async def test_filters_by_instance_index(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs", params={"app_key": "my_app", "instance_index": 0})
        assert response.status_code == 200
        data = response.json()
        names = [j["name"] for j in data]
        assert "my_app_job_i0" in names
        assert "my_app_job_i1" not in names
        assert "other_job" not in names

    async def test_filters_by_instance_index_1(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs", params={"app_key": "my_app", "instance_index": 1})
        assert response.status_code == 200
        data = response.json()
        names = [j["name"] for j in data]
        assert "my_app_job_i1" in names
        assert "my_app_job_i0" not in names

    async def test_response_uses_owner_id_field(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        # Verify the field is named owner_id, not owner
        first = data[0]
        assert "owner_id" in first
        assert "owner" not in first

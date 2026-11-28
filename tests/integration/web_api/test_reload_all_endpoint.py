"""POST /api/apps/reload (spec 162): 200 whenever the reload ran, with per-app outcomes and counts."""

from unittest.mock import AsyncMock, MagicMock

from httpx2 import AsyncClient

from hassette.schemas.app_outcomes import AppResult, OutcomeResult, ReconcileAction, ReconcileResult

from .conftest import outcome


class TestReloadAllEndpoint:
    """POST /api/apps/reload (spec 162): 200 whenever the reload ran, with per-app outcomes and counts."""

    async def test_partial_failure_still_answers_200_with_counts(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.reload_all = AsyncMock(
            return_value=ReconcileResult(
                apps={
                    "lights": AppResult(ReconcileAction.START, (outcome("lights"),)),
                    "door": AppResult(
                        ReconcileAction.RELOAD,
                        (outcome("door_a"), outcome("door_b", OutcomeResult.FAILED, "import failed")),
                    ),
                    "garage": AppResult(
                        ReconcileAction.STOP,
                        (outcome("garage", OutcomeResult.REFUSED, "needs a restart", needs_restart=True),),
                    ),
                }
            )
        )

        response = await client.post("/api/apps/reload")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["counts"] == {"succeeded": 1, "failed": 1, "refused": 1}
        assert [app["app_key"] for app in data["apps"]] == ["door", "garage", "lights"]
        assert data["apps"][0]["result"] == "failed"
        assert [app["action"] for app in data["apps"]] == ["reload", "stop", "start"]
        assert data["apps"][0]["outcomes"][1]["reason"] == "import failed"
        mock_hassette.app_handler.reload_all.assert_awaited_once_with(wait=False)

    async def test_wait_passes_through(self, client: AsyncClient, mock_hassette: MagicMock) -> None:
        mock_hassette.app_handler.reload_all = AsyncMock(return_value=ReconcileResult())

        response = await client.post("/api/apps/reload", params={"wait": "true"})

        assert response.status_code == 200, response.text
        assert response.json() == {"apps": [], "counts": {"succeeded": 0, "failed": 0, "refused": 0}}
        mock_hassette.app_handler.reload_all.assert_awaited_once_with(wait=True)

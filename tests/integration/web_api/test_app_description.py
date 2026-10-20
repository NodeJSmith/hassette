"""``AppManifest.description`` reaches ``GET /api/apps`` and ``GET /api/apps/{app_key}``."""

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.config.classes import AppManifest
from hassette.core.app_registry import AppRegistry
from tests.support.web_manifest_helpers import make_manifest_db_row

if TYPE_CHECKING:
    from httpx2 import AsyncClient

APP_KEY = "porch_light"
DESCRIPTION = "Turns on the porch light at sunset"


def seed_registry(mock_hassette: MagicMock, tmp_path: Path, description: str | None) -> None:
    """Wire a real ``AppRegistry`` holding one configured app, plus its persisted DB row."""
    manifest = AppManifest(
        app_key=APP_KEY,
        filename="porch_light.py",
        class_name="PorchLight",
        app_dir=tmp_path,
        full_path=tmp_path / "porch_light.py",
        description=description,
        app_config={"instance_name": APP_KEY},
    )
    registry = AppRegistry()
    registry.set_manifests({APP_KEY: manifest})
    mock_hassette._app_handler.registry = registry

    row = make_manifest_db_row(app_key=APP_KEY, display_name=manifest.display_name)
    mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(return_value=[row])
    mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(return_value=row)


@pytest.mark.parametrize("description", [DESCRIPTION, None])
async def test_description_served_by_app_list_and_detail(
    client: "AsyncClient", mock_hassette: MagicMock, tmp_path: Path, description: str | None
) -> None:
    seed_registry(mock_hassette, tmp_path, description)

    list_resp = await client.get("/api/apps")
    detail_resp = await client.get(f"/api/apps/{APP_KEY}")

    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200
    listed = next(a for a in list_resp.json()["apps"] if a["app_key"] == APP_KEY)
    for body in (listed, detail_resp.json()):
        assert "description" in body
        assert body["description"] == description
        assert body["in_current_config"] is True


async def test_description_is_null_for_db_only_app(client: "AsyncClient", mock_hassette: MagicMock) -> None:
    """An app known only from recorded history has no live manifest, so no description."""
    mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(
        return_value=make_manifest_db_row(app_key=APP_KEY, display_name="Porch Light")
    )

    resp = await client.get(f"/api/apps/{APP_KEY}")

    assert resp.status_code == 200
    assert resp.json()["in_current_config"] is False
    assert resp.json()["description"] is None

"""Integration tests for GET /api/apps/{app_key}/source."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from httpx2 import AsyncClient, Response

from tests.integration.conftest import make_manifest_mock

SAMPLE_SOURCE = """\
from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        pass
"""

APP_SOURCE_PATH = "/api/apps/my_app/source"


async def get_app_source(client: AsyncClient, mock_hassette: MagicMock, *, app_dir: Path, full_path: Path) -> Response:
    """Point the registry at a manifest for `full_path` under `app_dir`, then GET the source route.

    What varies between these tests is the on-disk layout (file present, file missing, file
    outside `app_dir`), so each test builds its own temp tree and hands the two resolved paths
    here rather than describing the layout through helper flags.
    """
    mock_hassette._app_handler.registry.get_manifest.return_value = make_manifest_mock(
        app_key="my_app",
        filename=full_path.name,
        app_dir=app_dir,
        full_path=full_path,
    )
    return await client.get(APP_SOURCE_PATH)


class TestAppSourceEndpoint:
    """Tests for GET /api/apps/{app_key}/source."""

    async def test_valid_app_returns_source(self, client, mock_hassette) -> None:
        """Returns 200 with source content for a valid app."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            src_file = app_dir / "my_app.py"
            src_file.write_text(SAMPLE_SOURCE)

            response = await get_app_source(client, mock_hassette, app_dir=app_dir, full_path=src_file)

        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["filename"] == "my_app.py"
        assert "class MyApp" in data["content"]
        assert data["line_count"] == len(SAMPLE_SOURCE.splitlines())

    async def test_unknown_app_returns_404(self, client, mock_hassette) -> None:
        """Returns 404 when app_key is not in the registry."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None

        response = await client.get("/api/apps/nonexistent/source")

        assert response.status_code == 404

    async def test_missing_file_returns_404(self, client, mock_hassette) -> None:
        """Returns 404 when the source file doesn't exist on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            missing_file = app_dir / "missing_app.py"  # deliberately not created

            response = await get_app_source(client, mock_hassette, app_dir=app_dir, full_path=missing_file)

        assert response.status_code == 404

    async def test_path_traversal_returns_403(self, client, mock_hassette) -> None:
        """Returns 403 when full_path resolves outside the app_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "apps"
            app_dir.mkdir()
            # full_path is outside app_dir (traversal attempt)
            outside_file = Path(tmpdir) / "secret.py"
            outside_file.write_text("SECRET = 'password'")

            response = await get_app_source(client, mock_hassette, app_dir=app_dir, full_path=outside_file)

        assert response.status_code == 403

    async def test_invalid_app_key_returns_400(self, client) -> None:
        """Invalid app_key format returns 400."""
        response = await client.get("/api/apps/!!bad!!/source")

        assert response.status_code == 400

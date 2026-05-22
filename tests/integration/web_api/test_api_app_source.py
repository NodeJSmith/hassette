"""Integration tests for GET /api/apps/{app_key}/source."""

import tempfile
from pathlib import Path

from tests.integration.conftest import make_manifest_mock

SAMPLE_SOURCE = """\
from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        pass
"""


class TestAppSourceEndpoint:
    """Tests for GET /api/apps/{app_key}/source."""

    async def test_valid_app_returns_source(self, client, mock_hassette) -> None:
        """Returns 200 with source content for a valid app."""

        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            src_file = app_dir / "my_app.py"
            src_file.write_text(SAMPLE_SOURCE)

            manifest = make_manifest_mock(
                app_key="my_app",
                filename="my_app.py",
                app_dir=app_dir,
                full_path=src_file,
            )
            mock_hassette._app_handler.registry.get_manifest.return_value = manifest

            response = await client.get("/api/apps/my_app/source")

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
            # File deliberately not created
            src_file = app_dir / "missing_app.py"

            manifest = make_manifest_mock(
                app_key="my_app",
                filename="missing_app.py",
                app_dir=app_dir,
                full_path=src_file,
            )
            mock_hassette._app_handler.registry.get_manifest.return_value = manifest

            response = await client.get("/api/apps/my_app/source")

        assert response.status_code == 404

    async def test_path_traversal_returns_403(self, client, mock_hassette) -> None:
        """Returns 403 when full_path resolves outside the app_dir."""

        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir) / "apps"
            app_dir.mkdir()
            # full_path is outside app_dir (traversal attempt)
            outside_file = Path(tmpdir) / "secret.py"
            outside_file.write_text("SECRET = 'password'")

            manifest = make_manifest_mock(
                app_key="my_app",
                filename="secret.py",
                app_dir=app_dir,
                full_path=outside_file,
            )
            mock_hassette._app_handler.registry.get_manifest.return_value = manifest

            response = await client.get("/api/apps/my_app/source")

        assert response.status_code == 403

    async def test_invalid_app_key_returns_400(self, client) -> None:
        """Invalid app_key format returns 400."""
        response = await client.get("/api/apps/!!bad!!/source")

        assert response.status_code == 400

"""Shared fixtures for integration tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.test_utils.web_mocks import create_mock_data_sync_service
from hassette.web.app import create_fastapi_app


@pytest.fixture
def data_sync_service(mock_hassette):
    """Create a DataSyncService with mocked Hassette."""
    return create_mock_data_sync_service(mock_hassette)


@pytest.fixture
def app(mock_hassette, data_sync_service):  # noqa: ARG001
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

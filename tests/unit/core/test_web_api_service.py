"""Unit tests for WebApiService uvicorn configuration and shutdown."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.core import Hassette
from hassette.core.web_api_service import WebApiService


@pytest.fixture
def web_api_service(unused_tcp_port_factory) -> WebApiService:
    from tests.conftest import TestConfig

    config = TestConfig(web_api={"port": unused_tcp_port_factory()})
    hassette = Hassette(config)
    return WebApiService(hassette)


class TestUvicornConfig:
    async def test_uses_websockets_sansio_protocol(self, web_api_service: WebApiService) -> None:
        with patch("hassette.core.web_api_service.uvicorn") as mock_uvicorn:
            mock_server = MagicMock()
            mock_server.serve = AsyncMock()
            mock_uvicorn.Server.return_value = mock_server

            await web_api_service.serve()

            config_call = mock_uvicorn.Config.call_args
            assert config_call.kwargs["ws"] == "websockets-sansio"


class TestShutdownSocketCleanup:
    async def test_cancellation_calls_server_shutdown(self, web_api_service: WebApiService) -> None:
        with patch("hassette.core.web_api_service.uvicorn") as mock_uvicorn:
            mock_server = MagicMock()
            mock_server.serve = AsyncMock(side_effect=asyncio.CancelledError)
            mock_server.shutdown = AsyncMock()
            mock_uvicorn.Server.return_value = mock_server

            with pytest.raises(asyncio.CancelledError):
                await web_api_service.serve()

            mock_server.shutdown.assert_awaited_once()

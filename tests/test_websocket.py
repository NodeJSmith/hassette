from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from hassette.core.services.websocket_service import _Websocket
from hassette.exceptions import FailedMessageError


class _WSOk:  # type: ignore[reportUnusedClass]
    def __init__(self):
        self.sent = []
        self.connected = True

    async def send_json(self, data):
        self.sent.append(data)

    @property
    def closed(self):
        return False


class _WSBoom:
    async def send_json(self, data):
        raise RuntimeError("boom")

    @property
    def closed(self):
        return False

    @property
    def connected(self):
        return True


async def test_ws_send_json_assigns_id():
    with patch(
        "hassette.core.services.websocket_service._Websocket.connected", new_callable=PropertyMock, return_value=True
    ):
        mock = AsyncMock()
        mock.config.websocket_log_level = "DEBUG"
        svc = _Websocket(mock)

        svc._ws = AsyncMock()
        await svc.send_json(type="ping")

        svc._ws.send_json.assert_called_once_with({"type": "ping", "id": 1})


async def test_ws_send_json_wraps_errors():
    with patch(
        "hassette.core.services.websocket_service._Websocket.connected", new_callable=PropertyMock, return_value=True
    ):
        mock = AsyncMock()
        mock.config.websocket_log_level = "DEBUG"
        svc = _Websocket(mock)

        svc._ws = _WSBoom()  # type: ignore[attr-defined]
        with pytest.raises(FailedMessageError):
            await svc.send_json(type="ping")

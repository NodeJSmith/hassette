from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from hassette.core.core import Hassette
from hassette.core.websocket import _Websocket
from hassette.exceptions import FailedMessageError


class _WSOk:
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
    with patch("hassette.core.websocket._Websocket.connected", new_callable=PropertyMock, return_value=True):
        svc = _Websocket(AsyncMock())
        svc._ws = AsyncMock()

        await svc.send_json(type="ping")

        svc._ws.send_json.assert_called_once_with({"type": "ping", "id": 1})


async def test_ws_send_json_wraps_errors(hassette_core: Hassette):
    with patch("hassette.core.websocket._Websocket.connected", new_callable=PropertyMock, return_value=True):
        svc = _Websocket(hassette_core)
        svc._ws = _WSBoom()  # type: ignore[attr-defined]
        with pytest.raises(FailedMessageError):
            await svc.send_json(type="ping")

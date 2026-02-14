"""Unit tests for WebSocket helper functions in hassette.web.routes.ws."""

import pytest
from starlette.websockets import WebSocketDisconnect

from hassette.web.routes.ws import _is_disconnect


class TestIsDisconnect:
    """Tests for the _is_disconnect() helper."""

    @pytest.mark.parametrize(
        "exc",
        [
            WebSocketDisconnect(),
            ConnectionResetError("reset"),
            BrokenPipeError("pipe"),
        ],
        ids=["WebSocketDisconnect", "ConnectionResetError", "BrokenPipeError"],
    )
    def test_typed_disconnect_errors(self, exc: BaseException) -> None:
        assert _is_disconnect(exc) is True

    def test_anyio_closed_resource_error(self) -> None:
        import anyio

        assert _is_disconnect(anyio.ClosedResourceError()) is True

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Unexpected ASGI message 'websocket.send'", True),
            ("Cannot call websocket.close after sending", True),
            ("websocket.send failed", True),
            ("websocket.close already done", True),
            ("Something unrelated", False),
        ],
        ids=["ws.send", "ws.close-after", "ws.send-failed", "ws.close-done", "unrelated"],
    )
    def test_runtime_error_message_matching(self, message: str, expected: bool) -> None:
        assert _is_disconnect(RuntimeError(message)) is expected

    def test_generic_runtime_error_is_not_disconnect(self) -> None:
        assert _is_disconnect(RuntimeError("generic error")) is False

    def test_value_error_is_not_disconnect(self) -> None:
        assert _is_disconnect(ValueError("bad value")) is False

    def test_type_error_is_not_disconnect(self) -> None:
        assert _is_disconnect(TypeError("wrong type")) is False

    def test_os_error_is_not_disconnect(self) -> None:
        assert _is_disconnect(OSError("os fail")) is False

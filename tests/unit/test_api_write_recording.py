"""Each named Api write records one row at send and resolves it by one owner (spec 149 D1, D3, D4, D8).

The transport is mocked at ``Api._api_service.ws_conn`` (WebSocket) or ``rest_request`` (REST), and the
recorder's repository is a mock, so these tests pin what each write records and which outcome each failure
maps to, not the SQL.
"""

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from pydantic import SecretStr

from hassette.api import Api
from hassette.api.helpers import HelperClient
from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.api_write_recorder import API_WRITE_DATA_MAX_CHARS, ApiWriteRecorder, ApiWriteRow
from hassette.core.pipeline_counters import PipelineCounter, PipelineCounters
from hassette.exceptions import (
    CommandNotSentError,
    CommandRejectedError,
    EntityNotFoundError,
    HttpRequestError,
    ResponseLostError,
    ResponseTimeoutError,
)
from hassette.models.helpers import CreateInputBooleanParams, UpdateInputBooleanParams
from tests.support.factories import make_app
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.conftest import make_api

APP_KEY = "porch"
INSTANCE = "main"


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


class Recorded:
    """An app-owned Api whose recorder's repository and transport are mocks, plus what it recorded."""

    def __init__(self) -> None:
        self.api = make_api()
        hassette: Any = self.api.hassette
        hassette.pipeline_counters = PipelineCounters()
        hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds = 30.0
        hassette.try_session_id.return_value = 7
        hassette.database_service.enqueue = MagicMock(return_value=True)
        self.recorder = ApiWriteRecorder(hassette)
        self.recorder.repository = MagicMock()
        hassette.api_write_recorder = self.recorder
        self.api.record_writes_for(APP_KEY, INSTANCE)
        # Use the real transport methods, over a mocked connection.
        del self.api.ws_send_and_wait
        del self.api.ws_send_json
        self.ws = MagicMock()
        self.ws.is_connected = True
        self.ws.send_and_wait = AsyncMock(return_value={"context": {"id": "ctx-1"}})
        self.ws.send_json = AsyncMock()
        self.ws.send_fire_and_forget = AsyncMock()
        self.api._api_service = MagicMock()
        self.api._api_service.ws_conn = self.ws

    @property
    def rows(self) -> list[ApiWriteRow]:
        return [c.args[0] for c in self.recorder.repository.insert_api_write.call_args_list]

    @property
    def row(self) -> ApiWriteRow:
        (row,) = self.rows
        return row

    @property
    def outcomes(self) -> list[dict[str, Any]]:
        return [c.kwargs for c in self.recorder.repository.update_api_write_outcome.call_args_list]

    def on_resolve(self) -> Callable[..., None]:
        """The resolve callback the transport was handed for the last awaited write."""
        assert self.ws.send_and_wait.await_args is not None
        return self.ws.send_and_wait.await_args.kwargs["on_resolve"]


@pytest.fixture
def rec() -> Recorded:
    return Recorded()


class TestWhatEachWriteRecords:
    async def test_call_service_normalizes_target_and_keeps_secrets_masked(self, rec: Recorded) -> None:
        await rec.api.call_service(
            "lock",
            "unlock",
            target={"entity_id": "lock.front"},
            area_id="porch",
            code=SecretStr("1234"),
        )

        row = rec.row
        assert (row.kind, row.operation) == ("call_service", "lock.unlock")
        assert row.target == {"entity_id": ["lock.front"], "area_id": ["porch"]}
        assert row.data == '{"code":"**********"}'
        assert (row.app_key, row.instance_name, row.session_id) == (APP_KEY, INSTANCE, 7)

    async def test_entity_id_in_service_data_lands_in_target(self, rec: Recorded) -> None:
        await rec.api.call_service("light", "turn_on", entity_id="light.a, Light.B", brightness=10)

        assert rec.row.target == {"entity_id": ["light.a", "light.b"]}
        assert rec.row.data == '{"brightness":10}'

    async def test_target_replaces_the_same_key_in_service_data(self, rec: Recorded) -> None:
        await rec.api.call_service("light", "turn_on", target={"entity_id": "light.a"}, entity_id="light.z")

        assert rec.row.target == {"entity_id": ["light.a"]}
        assert rec.row.data is None

    async def test_turn_on_records_once_as_call_service(self, rec: Recorded) -> None:
        await rec.api.turn_on("light.kitchen")

        assert (rec.row.kind, rec.row.operation, rec.row.target) == (
            "call_service",
            "light.turn_on",
            {"entity_id": ["light.kitchen"]},
        )

    async def test_fire_event_records_event_type_and_data(self, rec: Recorded) -> None:
        await rec.api.fire_event("doorbell", {"who": "mail"})

        assert (rec.row.kind, rec.row.operation, rec.row.target, rec.row.data) == (
            "fire_event",
            "doorbell",
            None,
            '{"who":"mail"}',
        )

    async def test_helper_writes(self, rec: Recorded) -> None:
        helpers = HelperClient.__new__(HelperClient)  # bypass Resource wiring; only _api and logger are read
        helpers._api = rec.api
        helpers.logger = rec.api.logger
        rec.api.helpers = helpers
        rec.ws.send_and_wait.return_value = {"id": "away", "name": "Away"}
        await rec.api.helpers.create(CreateInputBooleanParams(name="Away"))
        await rec.api.helpers.update("away", UpdateInputBooleanParams(name="Gone"))
        rec.ws.send_and_wait.return_value = None
        await rec.api.helpers.delete("input_boolean", "away")

        assert [(r.kind, r.operation, r.target, r.data) for r in rec.rows] == [
            ("helper_create", "input_boolean", None, '{"name":"Away"}'),
            ("helper_update", "input_boolean", {"helper_id": ["away"]}, '{"name":"Gone"}'),
            ("helper_delete", "input_boolean", {"helper_id": ["away"]}, None),
        ]

    async def test_data_is_cut_at_the_limit(self, rec: Recorded) -> None:
        await rec.api.fire_event("big", {"text": "x" * 5000})

        assert rec.row.data is not None
        assert len(rec.row.data) == API_WRITE_DATA_MAX_CHARS
        assert rec.row.data.endswith("…")

    async def test_execution_id_is_captured_at_send(self, rec: Recorded) -> None:
        token = CURRENT_EXECUTION_ID.set("exec-1")
        try:
            await rec.api.fire_event("doorbell")
        finally:
            CURRENT_EXECUTION_ID.reset(token)

        assert rec.row.execution_id == "exec-1"

    async def test_unowned_api_records_nothing(self, rec: Recorded) -> None:
        rec.api._write_owner = None

        await rec.api.fire_event("doorbell")

        rec.recorder.repository.insert_api_write.assert_not_called()
        assert rec.ws.send_and_wait.await_args is not None
        assert rec.ws.send_and_wait.await_args.kwargs["on_resolve"] is None

    async def test_insert_is_enqueued_before_the_send(self, rec: Recorded) -> None:
        """FIFO order on the write queue then puts the insert ahead of any update the reply causes."""
        order: list[str] = []
        rec.recorder.repository.insert_api_write.side_effect = lambda _row: order.append("insert")
        rec.ws.send_and_wait.side_effect = lambda **_: order.append("send")

        await rec.api.fire_event("doorbell")

        assert order == ["insert", "send"]


class TestWebSocketOwnership:
    async def test_fire_and_forget_call_hands_its_record_to_the_transport(self, rec: Recorded) -> None:
        await rec.api.call_service("light", "turn_on", target={"entity_id": "light.a"})

        rec.ws.send_json.assert_not_awaited()
        assert rec.ws.send_fire_and_forget.await_args is not None
        on_resolve = rec.ws.send_fire_and_forget.await_args.args[0]
        assert rec.outcomes == []  # the caller writes nothing; the entry resolves it later
        on_resolve("success", context_id="ctx-9")
        assert rec.outcomes == [
            {
                "outcome": "success",
                "context_id": "ctx-9",
                "error_code": None,
                "error_message": None,
                "resolved_ts": rec.outcomes[0]["resolved_ts"],
            }
        ]

    @pytest.mark.parametrize("wait", [{"wait_for_ack": True}, {"return_response": True}])
    async def test_awaited_call_hands_its_record_to_the_transport(self, rec: Recorded, wait: dict) -> None:
        rec.ws.send_and_wait.return_value = {"context": {"id": "ctx-1"}, "response": {}}

        await rec.api.call_service("script", "turn_on", **wait)

        assert rec.ws.send_and_wait.await_args is not None
        assert rec.ws.send_and_wait.await_args.kwargs["retry_on_timeout"] is False
        assert rec.outcomes == []

    @pytest.mark.parametrize(
        "exc",
        [
            CommandRejectedError("nope", code="not_found"),
            ResponseTimeoutError("slow"),
            ResponseLostError("gone"),
            asyncio.CancelledError(),
        ],
        ids=["rejected", "timeout", "lost", "cancelled"],
    )
    async def test_caller_writes_nothing_once_sent(self, rec: Recorded, exc: BaseException) -> None:
        rec.ws.send_and_wait.side_effect = exc

        with pytest.raises(type(exc)):
            await rec.api.fire_event("doorbell")

        assert rec.outcomes == []

    async def test_not_sent_is_the_callers_to_record(self, rec: Recorded) -> None:
        rec.ws.send_and_wait.side_effect = CommandNotSentError("down")

        with pytest.raises(CommandNotSentError):
            await rec.api.fire_event("doorbell")

        assert [o["outcome"] for o in rec.outcomes] == ["not_sent"]

    async def test_disconnected_api_records_not_sent_for_fire_and_forget(self, rec: Recorded) -> None:
        rec.ws.is_connected = False

        with pytest.raises(CommandNotSentError):
            await rec.api.call_service("light", "turn_on")

        assert [o["outcome"] for o in rec.outcomes] == ["not_sent"]
        rec.ws.send_fire_and_forget.assert_not_awaited()


class TestRejectedCallWarning:
    def handle(self, rec: Recorded, *, fire_and_forget: bool) -> Any:
        token = CURRENT_EXECUTION_ID.set("exec-7")
        try:
            return rec.recorder.begin(
                api_logger=rec.api.logger,
                app_key=APP_KEY,
                instance_name=INSTANCE,
                kind="call_service",
                operation="light.turn_on",
                target={"entity_id": ["light.secret_room"]},
                data=None,
                fire_and_forget=fire_and_forget,
            )
        finally:
            CURRENT_EXECUTION_ID.reset(token)

    async def test_fire_and_forget_rejection_warns_under_its_execution(self, rec: Recorded) -> None:
        seen: list[str | None] = []
        rec.api.logger = MagicMock()
        rec.api.logger.warning.side_effect = lambda *_a, **_k: seen.append(CURRENT_EXECUTION_ID.get())
        handle = self.handle(rec, fire_and_forget=True)

        handle.resolve("rejected", error_code="not_found", error_message="no such service")

        assert seen == ["exec-7"]
        assert CURRENT_EXECUTION_ID.get() is None
        rendered = rec.api.logger.warning.call_args.args[0] % rec.api.logger.warning.call_args.args[1:]
        assert "light.turn_on" in rendered
        assert "not_found" in rendered
        assert "exec-7" in rendered
        assert handle.write_id in rendered
        assert "secret_room" not in rendered

    async def test_awaited_rejection_does_not_warn(self, rec: Recorded) -> None:
        rec.api.logger = MagicMock()
        handle = self.handle(rec, fire_and_forget=False)

        handle.resolve("rejected", error_code="not_found", error_message="x")

        rec.api.logger.warning.assert_not_called()


class TestRestOwnership:
    async def test_set_state_records_target_and_returned_context(self, rec: Recorded) -> None:
        response = AsyncMock()
        response.json = AsyncMock(return_value={"state": "on", "context": {"id": "ctx-5"}})
        rec.api.post_rest_request = AsyncMock(return_value=response)

        await rec.api.set_state("sensor.x", "on", {"unit": "W"})

        assert (rec.row.kind, rec.row.operation, rec.row.target) == ("set_state", None, {"entity_id": ["sensor.x"]})
        assert rec.row.data == '{"state":"on","attributes":{"unit":"W"}}'
        assert [(o["outcome"], o["context_id"]) for o in rec.outcomes] == [("success", "ctx-5")]

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (CommandNotSentError("no session"), ("not_sent", None)),
            (EntityNotFoundError("gone"), ("rejected", "404")),
            (HttpRequestError(400, "Bad Request", method="POST", url="states/x"), ("rejected", "400")),
            (ResponseTimeoutError("slow"), ("connection_lost", None)),
            (aiohttp.ClientPayloadError("cut"), ("connection_lost", None)),
            (asyncio.CancelledError(), ("connection_lost", None)),
        ],
        ids=["not-sent", "404", "http-error", "timeout", "body-read", "cancelled"],
    )
    async def test_post_failure_maps_to_one_outcome(
        self, rec: Recorded, exc: BaseException, expected: tuple[str, str | None]
    ) -> None:
        rec.api.post_rest_request = AsyncMock(side_effect=exc)

        with pytest.raises(type(exc)):
            await rec.api.set_state("sensor.x", "on")

        assert [(o["outcome"], o["error_code"]) for o in rec.outcomes] == [expected]

    async def test_failed_preliminary_get_is_not_sent(self, rec: Recorded) -> None:
        rec.api.rest_request = AsyncMock(side_effect=ResponseTimeoutError("slow"))

        with pytest.raises(ResponseTimeoutError):
            await rec.api.set_state("sensor.x", "on")

        assert [o["outcome"] for o in rec.outcomes] == ["not_sent"]

    async def test_delete_entity_records_success(self, rec: Recorded) -> None:
        response = MagicMock(status=204)
        rec.api.rest_request = AsyncMock(return_value=response)

        await rec.api.delete_entity("sensor.x")

        assert (rec.row.kind, rec.row.target) == ("delete_entity", {"entity_id": ["sensor.x"]})
        assert [o["outcome"] for o in rec.outcomes] == ["success"]


class TestDrops:
    def test_full_queue_counts_and_warns_once_per_episode(self, rec: Recorded) -> None:
        rec.api.hassette.database_service.enqueue = MagicMock(return_value=False)
        rec.recorder.logger = MagicMock()

        for _ in range(3):
            rec.recorder.enqueue(MagicMock())

        assert rec.api.hassette.pipeline_counters.get(PipelineCounter.API_WRITE_RECORD_DROPPED) == 3
        rec.recorder.logger.warning.assert_called_once()

    def test_queue_not_live_drops_quietly(self, rec: Recorded) -> None:
        rec.api.hassette.database_service.enqueue = MagicMock(side_effect=RuntimeError("not ready"))

        rec.recorder.enqueue(MagicMock())

        assert rec.api.hassette.pipeline_counters.get(PipelineCounter.API_WRITE_RECORD_DROPPED) == 0


def test_app_turns_on_recording_for_its_own_api() -> None:
    app = make_app(app_key=APP_KEY, instance_name=INSTANCE)

    assert app.api._write_owner == (APP_KEY, INSTANCE)


def test_api_built_outside_an_app_records_nothing() -> None:
    hassette = make_mock_hassette(sealed=False)

    assert Api(hassette, parent=None)._write_owner is None

"""Integration tests for Api helper CRUD methods and module-level helpers.

Tests cover:
- Module-level helpers: _expect_list, _expect_dict, _ws_helper_call
- 32 CRUD methods (8 domains x 4 ops): transport-shape and return-type assertions
- 3 counter service-call shortcuts: correct call args + error propagation

Fixtures use AsyncMock to patch ws_send_and_wait on a live Api instance,
avoiding SimpleTestServer and its REST layer entirely. This is the correct
strategy because all helper CRUD uses the WebSocket path.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.api.api import Api, _expect_dict, _expect_list, _ws_helper_call
from hassette.exceptions import FailedMessageError
from hassette.models.helpers import (
    CounterRecord,
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputButtonParams,
    CreateInputDatetimeParams,
    CreateInputNumberParams,
    CreateInputSelectParams,
    CreateInputTextParams,
    CreateTimerParams,
    InputBooleanRecord,
    InputButtonRecord,
    InputDatetimeRecord,
    InputNumberRecord,
    InputSelectRecord,
    InputTextRecord,
    TimerRecord,
    UpdateCounterParams,
    UpdateInputBooleanParams,
    UpdateInputButtonParams,
    UpdateInputDatetimeParams,
    UpdateInputNumberParams,
    UpdateInputSelectParams,
    UpdateInputTextParams,
    UpdateTimerParams,
)
from hassette.models.services import ServiceResponse
from hassette.models.states.base import Context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def api(hassette_with_mock_api):
    """Return the Api instance from hassette_with_mock_api, ready for ws patching."""
    api_client, _ = hassette_with_mock_api
    return api_client


# ---------------------------------------------------------------------------
# Module-level helpers: _expect_list
# ---------------------------------------------------------------------------


def test_expect_list_passes_through_list():
    """_expect_list returns the list unchanged when val is a list."""
    val = [1, 2, 3]
    result = _expect_list(val, "ctx")
    assert result == [1, 2, 3]
    assert result is val  # identity preserved


def test_expect_list_raises_on_non_list():
    """_expect_list raises TypeError with context in the message when val is not a list."""
    with pytest.raises(TypeError) as exc_info:
        _expect_list({"x": 1}, "input_boolean/list")
    assert "input_boolean/list" in str(exc_info.value)
    assert "dict" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Module-level helpers: _expect_dict
# ---------------------------------------------------------------------------


def test_expect_dict_passes_through_dict():
    """_expect_dict returns the dict unchanged when val is a dict."""
    val = {"id": "x", "name": "Test"}
    result = _expect_dict(val, "ctx")
    assert result == {"id": "x", "name": "Test"}
    assert result is val  # identity preserved


def test_expect_dict_raises_on_non_dict():
    """_expect_dict raises TypeError with context in the message when val is not a dict."""
    with pytest.raises(TypeError) as exc_info:
        _expect_dict([1, 2], "input_number/create")
    assert "input_number/create" in str(exc_info.value)
    assert "list" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Module-level helpers: _ws_helper_call
# ---------------------------------------------------------------------------


async def test_ws_helper_call_propagates_success():
    """_ws_helper_call returns the ws_send_and_wait result on success."""
    mock_api = MagicMock(spec=Api)
    mock_api.ws_send_and_wait = AsyncMock(return_value={"id": "x"})

    result = await _ws_helper_call(mock_api, "d", "op")
    assert result == {"id": "x"}
    mock_api.ws_send_and_wait.assert_awaited_once_with(type="d/op")


async def test_ws_helper_call_chains_error_with_context():
    """_ws_helper_call re-raises FailedMessageError with domain/op context and preserves code/original_data."""
    original = FailedMessageError("orig", code="name_in_use", original_data={"a": 1})
    mock_api = MagicMock(spec=Api)
    mock_api.ws_send_and_wait = AsyncMock(side_effect=original)

    with pytest.raises(FailedMessageError) as exc_info:
        await _ws_helper_call(mock_api, "d", "op", key="val")
    e = exc_info.value
    assert "d/op failed for" in str(e)
    assert e.code == "name_in_use"
    assert e.original_data == {"a": 1}
    assert e.__cause__ is original


# ---------------------------------------------------------------------------
# input_boolean CRUD
# ---------------------------------------------------------------------------

_IB_RECORD = {"id": "vacation_mode", "name": "Vacation Mode", "initial": False}


async def test_list_input_booleans(api: Api):
    """list_input_booleans sends correct command and parses response."""
    api.ws_send_and_wait = AsyncMock(return_value=[_IB_RECORD])

    result = await api.list_input_booleans()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_boolean/list")
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], InputBooleanRecord)
    assert result[0].id == "vacation_mode"


async def test_create_input_boolean(api: Api):
    """create_input_boolean sends correct command with payload and parses response."""
    api.ws_send_and_wait = AsyncMock(return_value=_IB_RECORD)
    params = CreateInputBooleanParams(name="Vacation Mode", initial=False)

    result = await api.create_input_boolean(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_boolean/create"
    assert call_kwargs["name"] == "Vacation Mode"
    assert call_kwargs["initial"] is False
    # exclude_unset=True: icon was not set, so it should NOT be in the payload
    assert "icon" not in call_kwargs
    assert isinstance(result, InputBooleanRecord)
    assert result.id == "vacation_mode"


async def test_update_input_boolean(api: Api):
    """update_input_boolean sends correct command with domain_id key."""
    updated = {**_IB_RECORD, "name": "Holiday Mode"}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputBooleanParams(name="Holiday Mode")

    result = await api.update_input_boolean("vacation_mode", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_boolean/update"
    assert call_kwargs["input_boolean_id"] == "vacation_mode"
    assert call_kwargs["name"] == "Holiday Mode"
    assert isinstance(result, InputBooleanRecord)
    assert result.name == "Holiday Mode"


async def test_delete_input_boolean(api: Api):
    """delete_input_boolean sends correct command and returns None."""
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_boolean("vacation_mode")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_boolean/delete"
    assert call_kwargs["input_boolean_id"] == "vacation_mode"
    assert result is None


# ---------------------------------------------------------------------------
# input_number CRUD
# ---------------------------------------------------------------------------

_IN_RECORD = {"id": "brightness", "name": "Brightness", "min": 0.0, "max": 100.0}


async def test_list_input_numbers(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_IN_RECORD])

    result = await api.list_input_numbers()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_number/list")
    assert isinstance(result[0], InputNumberRecord)
    assert result[0].id == "brightness"


async def test_create_input_number(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_IN_RECORD)
    params = CreateInputNumberParams(name="Brightness", min=0.0, max=100.0)

    result = await api.create_input_number(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_number/create"
    assert call_kwargs["name"] == "Brightness"
    assert isinstance(result, InputNumberRecord)


async def test_update_input_number(api: Api):
    updated = {**_IN_RECORD, "max": 200.0}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputNumberParams(max=200.0)

    result = await api.update_input_number("brightness", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_number/update"
    assert call_kwargs["input_number_id"] == "brightness"
    assert isinstance(result, InputNumberRecord)


async def test_delete_input_number(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_number("brightness")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_number/delete"
    assert call_kwargs["input_number_id"] == "brightness"
    assert result is None


# ---------------------------------------------------------------------------
# input_text CRUD
# ---------------------------------------------------------------------------

_IT_RECORD = {"id": "wifi_password", "name": "WiFi Password"}


async def test_list_input_texts(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_IT_RECORD])

    result = await api.list_input_texts()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_text/list")
    assert isinstance(result[0], InputTextRecord)
    assert result[0].id == "wifi_password"


async def test_create_input_text(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_IT_RECORD)
    params = CreateInputTextParams(name="WiFi Password")

    result = await api.create_input_text(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_text/create"
    assert isinstance(result, InputTextRecord)


async def test_update_input_text(api: Api):
    updated = {**_IT_RECORD, "name": "Wifi Passphrase"}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputTextParams(name="Wifi Passphrase")

    result = await api.update_input_text("wifi_password", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_text/update"
    assert call_kwargs["input_text_id"] == "wifi_password"
    assert isinstance(result, InputTextRecord)


async def test_delete_input_text(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_text("wifi_password")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_text/delete"
    assert call_kwargs["input_text_id"] == "wifi_password"
    assert result is None


# ---------------------------------------------------------------------------
# input_select CRUD
# ---------------------------------------------------------------------------

_IS_RECORD = {"id": "theme", "name": "Theme", "options": ["light", "dark"]}


async def test_list_input_selects(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_IS_RECORD])

    result = await api.list_input_selects()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_select/list")
    assert isinstance(result[0], InputSelectRecord)
    assert result[0].id == "theme"
    assert result[0].options == ["light", "dark"]


async def test_create_input_select(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_IS_RECORD)
    params = CreateInputSelectParams(name="Theme", options=["light", "dark"])

    result = await api.create_input_select(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_select/create"
    assert call_kwargs["options"] == ["light", "dark"]
    assert isinstance(result, InputSelectRecord)


async def test_update_input_select(api: Api):
    updated = {**_IS_RECORD, "options": ["light", "dark", "auto"]}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputSelectParams(options=["light", "dark", "auto"])

    result = await api.update_input_select("theme", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_select/update"
    assert call_kwargs["input_select_id"] == "theme"
    assert isinstance(result, InputSelectRecord)


async def test_delete_input_select(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_select("theme")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_select/delete"
    assert call_kwargs["input_select_id"] == "theme"
    assert result is None


# ---------------------------------------------------------------------------
# input_datetime CRUD
# ---------------------------------------------------------------------------

_IDT_RECORD = {"id": "alarm_time", "name": "Alarm Time", "has_date": False, "has_time": True}


async def test_list_input_datetimes(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_IDT_RECORD])

    result = await api.list_input_datetimes()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_datetime/list")
    assert isinstance(result[0], InputDatetimeRecord)
    assert result[0].id == "alarm_time"


async def test_create_input_datetime(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_IDT_RECORD)
    params = CreateInputDatetimeParams(name="Alarm Time", has_time=True)

    result = await api.create_input_datetime(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_datetime/create"
    assert call_kwargs["has_time"] is True
    assert isinstance(result, InputDatetimeRecord)


async def test_update_input_datetime(api: Api):
    updated = {**_IDT_RECORD, "name": "Wake Up Time"}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputDatetimeParams(name="Wake Up Time")

    result = await api.update_input_datetime("alarm_time", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_datetime/update"
    assert call_kwargs["input_datetime_id"] == "alarm_time"
    assert isinstance(result, InputDatetimeRecord)


async def test_delete_input_datetime(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_datetime("alarm_time")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_datetime/delete"
    assert call_kwargs["input_datetime_id"] == "alarm_time"
    assert result is None


# ---------------------------------------------------------------------------
# input_button CRUD
# ---------------------------------------------------------------------------

_IBT_RECORD = {"id": "restart_btn", "name": "Restart"}


async def test_list_input_buttons(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_IBT_RECORD])

    result = await api.list_input_buttons()

    api.ws_send_and_wait.assert_awaited_once_with(type="input_button/list")
    assert isinstance(result[0], InputButtonRecord)
    assert result[0].id == "restart_btn"


async def test_create_input_button(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_IBT_RECORD)
    params = CreateInputButtonParams(name="Restart")

    result = await api.create_input_button(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_button/create"
    assert call_kwargs["name"] == "Restart"
    assert isinstance(result, InputButtonRecord)


async def test_update_input_button(api: Api):
    updated = {**_IBT_RECORD, "name": "Reboot Button"}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateInputButtonParams(name="Reboot Button")

    result = await api.update_input_button("restart_btn", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_button/update"
    assert call_kwargs["input_button_id"] == "restart_btn"
    assert isinstance(result, InputButtonRecord)


async def test_delete_input_button(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_input_button("restart_btn")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "input_button/delete"
    assert call_kwargs["input_button_id"] == "restart_btn"
    assert result is None


# ---------------------------------------------------------------------------
# counter CRUD
# ---------------------------------------------------------------------------

_CTR_RECORD = {"id": "motion_count", "name": "Motion Count", "initial": 0, "step": 1}


async def test_list_counters(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_CTR_RECORD])

    result = await api.list_counters()

    api.ws_send_and_wait.assert_awaited_once_with(type="counter/list")
    assert isinstance(result[0], CounterRecord)
    assert result[0].id == "motion_count"


async def test_create_counter(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_CTR_RECORD)
    params = CreateCounterParams(name="Motion Count", initial=0)

    result = await api.create_counter(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "counter/create"
    assert call_kwargs["name"] == "Motion Count"
    # counter uses minimum/maximum, not min/max
    assert "minimum" not in call_kwargs or call_kwargs.get("minimum") is None
    assert isinstance(result, CounterRecord)


async def test_update_counter(api: Api):
    updated = {**_CTR_RECORD, "maximum": 100}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateCounterParams(maximum=100)

    result = await api.update_counter("motion_count", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "counter/update"
    assert call_kwargs["counter_id"] == "motion_count"
    assert call_kwargs["maximum"] == 100
    assert isinstance(result, CounterRecord)


async def test_delete_counter(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_counter("motion_count")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "counter/delete"
    assert call_kwargs["counter_id"] == "motion_count"
    assert result is None


# ---------------------------------------------------------------------------
# timer CRUD
# ---------------------------------------------------------------------------

_TMR_RECORD = {"id": "cooldown", "name": "Cooldown Timer", "duration": "00:05:00"}


async def test_list_timers(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=[_TMR_RECORD])

    result = await api.list_timers()

    api.ws_send_and_wait.assert_awaited_once_with(type="timer/list")
    assert isinstance(result[0], TimerRecord)
    assert result[0].id == "cooldown"


async def test_create_timer(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=_TMR_RECORD)
    params = CreateTimerParams(name="Cooldown Timer", duration="00:05:00")

    result = await api.create_timer(params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "timer/create"
    assert call_kwargs["name"] == "Cooldown Timer"
    assert call_kwargs["duration"] == "00:05:00"
    assert isinstance(result, TimerRecord)


async def test_update_timer(api: Api):
    updated = {**_TMR_RECORD, "duration": "00:10:00"}
    api.ws_send_and_wait = AsyncMock(return_value=updated)
    params = UpdateTimerParams(duration="00:10:00")

    result = await api.update_timer("cooldown", params)

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "timer/update"
    assert call_kwargs["timer_id"] == "cooldown"
    assert call_kwargs["duration"] == "00:10:00"
    assert isinstance(result, TimerRecord)


async def test_delete_timer(api: Api):
    api.ws_send_and_wait = AsyncMock(return_value=None)

    result = await api.delete_timer("cooldown")

    call_kwargs = api.ws_send_and_wait.call_args.kwargs
    assert call_kwargs["type"] == "timer/delete"
    assert call_kwargs["timer_id"] == "cooldown"
    assert result is None


# ---------------------------------------------------------------------------
# Counter service-call shortcuts
# ---------------------------------------------------------------------------

_SERVICE_RESPONSE = ServiceResponse(context=Context(id="ctx-1"))


async def test_increment_counter_calls_service(api: Api):
    """increment_counter calls call_service with correct args and return_response=True."""
    api.call_service = AsyncMock(return_value=_SERVICE_RESPONSE)

    await api.increment_counter("counter.motion_count")

    api.call_service.assert_awaited_once_with(
        "counter",
        "increment",
        target={"entity_id": "counter.motion_count"},
        return_response=True,
    )


async def test_increment_counter_propagates_failed_message_error(api: Api):
    """increment_counter surfaces FailedMessageError from call_service."""
    error = FailedMessageError("transport fail", code="timeout")
    api.call_service = AsyncMock(side_effect=error)

    with pytest.raises(FailedMessageError) as exc_info:
        await api.increment_counter("counter.motion_count")
    assert exc_info.value is error


async def test_decrement_counter_calls_service(api: Api):
    """decrement_counter calls call_service with correct args and return_response=True."""
    api.call_service = AsyncMock(return_value=_SERVICE_RESPONSE)

    await api.decrement_counter("counter.motion_count")

    api.call_service.assert_awaited_once_with(
        "counter",
        "decrement",
        target={"entity_id": "counter.motion_count"},
        return_response=True,
    )


async def test_decrement_counter_propagates_failed_message_error(api: Api):
    """decrement_counter surfaces FailedMessageError from call_service."""
    error = FailedMessageError("transport fail", code="timeout")
    api.call_service = AsyncMock(side_effect=error)

    with pytest.raises(FailedMessageError):
        await api.decrement_counter("counter.motion_count")


async def test_reset_counter_calls_service(api: Api):
    """reset_counter calls call_service with correct args and return_response=True."""
    api.call_service = AsyncMock(return_value=_SERVICE_RESPONSE)

    await api.reset_counter("counter.motion_count")

    api.call_service.assert_awaited_once_with(
        "counter",
        "reset",
        target={"entity_id": "counter.motion_count"},
        return_response=True,
    )


async def test_reset_counter_propagates_failed_message_error(api: Api):
    """reset_counter surfaces FailedMessageError from call_service."""
    error = FailedMessageError("transport fail", code="timeout")
    api.call_service = AsyncMock(side_effect=error)

    with pytest.raises(FailedMessageError):
        await api.reset_counter("counter.motion_count")

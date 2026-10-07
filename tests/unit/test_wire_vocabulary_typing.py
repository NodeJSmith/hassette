"""Server-defined vocabularies on response fields are typed, open to unknown values, and defined once in wire."""

from collections.abc import Callable
from typing import Any, get_args

import hassette_wire
import pytest
from hassette_wire import (
    LENIENT_CONTEXT,
    ActionResponse,
    AppAction,
    AppListResponse,
    AppStatus,
    JobSummary,
    LogLevel,
    LogLevelRequest,
    LogLevelResponse,
    ResourceRole,
    ScheduleStatus,
    ScheduleStatusReason,
    ServiceInfo,
    ServiceStatusData,
    UnknownValue,
)
from pydantic import BaseModel, ValidationError

import hassette.scheduler
import hassette.scheduler.classes
import hassette.types
import hassette.types.enums
from hassette.cli.commands import app as cli_app
from hassette.web import dependencies
from hassette.web.routes import apps as apps_route
from tests.support.web_job_helpers import make_job_summary


def job_summary_body(**overrides: Any) -> dict[str, Any]:
    return make_job_summary().model_dump(mode="json") | overrides


def service_info_body(**overrides: Any) -> dict[str, Any]:
    return {"name": "WebsocketService", "status": "running", "role": "service"} | overrides


def service_status_body(**overrides: Any) -> dict[str, Any]:
    return {"resource_name": "WebsocketService", "role": "service", "status": "running"} | overrides


def action_body(**overrides: Any) -> dict[str, Any]:
    return {"app_key": "lights", "action": "start", "instance_index": None} | overrides


def app_list_body(status_counts: dict[str, int]) -> dict[str, Any]:
    return {"total": 0, "status_counts": status_counts, "apps": []}


# (model, body builder, field, out-of-vocabulary value) for every newly typed open field.
OPEN_FIELDS = [
    (JobSummary, job_summary_body, "schedule_status", "paused"),
    (JobSummary, job_summary_body, "schedule_status_reason", "user_paused"),
    (ServiceInfo, service_info_body, "role", "plugin"),
    (ServiceStatusData, service_status_body, "role", "plugin"),
    (ActionResponse, action_body, "action", "pause"),
]
BodyBuilder = Callable[..., dict[str, Any]]
OPEN_FIELD_IDS = [f"{model.__name__}.{field}" for model, _, field, _ in OPEN_FIELDS]


@pytest.mark.parametrize(("model", "body", "field", "unknown"), OPEN_FIELDS, ids=OPEN_FIELD_IDS)
def test_unknown_value_is_rejected_strictly(
    model: type[BaseModel], body: BodyBuilder, field: str, unknown: str
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(body(**{field: unknown}))


@pytest.mark.parametrize(("model", "body", "field", "unknown"), OPEN_FIELDS, ids=OPEN_FIELD_IDS)
def test_unknown_value_parses_leniently(model: type[BaseModel], body: BodyBuilder, field: str, unknown: str) -> None:
    parsed = model.model_validate(body(**{field: unknown}), context=LENIENT_CONTEXT)

    value = getattr(parsed, field)
    assert isinstance(value, UnknownValue)
    assert value == unknown


def test_schedule_status_parses_to_members() -> None:
    parsed = JobSummary.model_validate(
        job_summary_body(schedule_status="completed", schedule_status_reason="trigger_error")
    )

    assert parsed.schedule_status is ScheduleStatus.COMPLETED
    assert parsed.schedule_status_reason is ScheduleStatusReason.TRIGGER_ERROR


def test_schedule_status_is_required() -> None:
    body = job_summary_body()
    del body["schedule_status"]

    with pytest.raises(ValidationError, match="schedule_status"):
        JobSummary.model_validate(body)


def test_service_info_role_is_required() -> None:
    body = service_info_body()
    del body["role"]

    with pytest.raises(ValidationError, match="role"):
        ServiceInfo.model_validate(body)


def test_service_info_role_rejects_the_old_empty_string_sentinel() -> None:
    with pytest.raises(ValidationError):
        ServiceInfo.model_validate(service_info_body(role=""))


def test_status_counts_keys_parse_to_app_status() -> None:
    parsed = AppListResponse.model_validate(app_list_body({"running": 2, "failed": 1}))

    assert parsed.status_counts == {AppStatus.RUNNING: 2, AppStatus.FAILED: 1}
    assert all(isinstance(key, AppStatus) for key in parsed.status_counts)


def test_status_counts_unknown_key_is_rejected_strictly() -> None:
    with pytest.raises(ValidationError):
        AppListResponse.model_validate(app_list_body({"running": 2, "paused": 1}))


def test_status_counts_unknown_key_parses_leniently_and_round_trips() -> None:
    body = app_list_body({"running": 2, "paused": 1})

    parsed = AppListResponse.model_validate(body, context=LENIENT_CONTEXT)

    unknown_keys = [key for key in parsed.status_counts if isinstance(key, UnknownValue)]
    assert unknown_keys == ["paused"]
    assert parsed.model_dump(mode="json")["status_counts"] == body["status_counts"]


@pytest.mark.parametrize("level", ["debug", "WARN", ""])
def test_effective_level_accepts_only_the_five_standard_names(level: str) -> None:
    with pytest.raises(ValidationError):
        LogLevelResponse(logger="hassette", effective_level=level)  # pyright: ignore[reportArgumentType]


def test_log_level_request_still_accepts_any_case() -> None:
    assert LogLevelRequest(logger="hassette", level="debug").level == "debug"


def test_public_hassette_names_resolve_to_the_wire_vocabularies() -> None:
    """``hassette.types.ResourceRole`` and ``hassette.scheduler.ScheduleStatus*`` are public API backed by wire."""
    assert hassette.types.enums.ResourceRole is hassette.types.ResourceRole is hassette_wire.ResourceRole
    assert (
        hassette.scheduler.classes.ScheduleStatus is hassette.scheduler.ScheduleStatus is hassette_wire.ScheduleStatus
    )
    assert (
        hassette.scheduler.classes.ScheduleStatusReason
        is hassette.scheduler.ScheduleStatusReason
        is hassette_wire.ScheduleStatusReason
    )


def test_resource_role_values_are_unchanged() -> None:
    assert [role.value for role in ResourceRole] == ["core", "base", "service", "resource", "app", "unknown"]


def test_server_log_level_names_equal_the_wire_vocabulary() -> None:
    assert set(dependencies.LOG_LEVELS) == set(get_args(LogLevel))


@pytest.mark.parametrize("past_tense", [cli_app.ACTION_PAST_TENSE, apps_route._ACTION_PAST_TENSE], ids=["cli", "route"])
def test_action_past_tense_covers_every_app_action(past_tense: dict[AppAction, str]) -> None:
    assert set(past_tense) == set(get_args(AppAction))

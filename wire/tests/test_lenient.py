import copy
import json
import pickle
import warnings
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, get_args, get_origin

import hassette_wire
import pytest
from hassette_wire import (
    LENIENT_CONTEXT,
    AppStatus,
    AppStatusChangedData,
    AppSummary,
    BlockingHandlerRef,
    ExecutionMode,
    ListenerWithSummary,
    LogLevel,
    LogLevelRequest,
    ProblemCode,
    ProblemDetail,
    ResourceStatus,
    ServiceInfoResponse,
    SessionRequest,
    SourceTier,
    SystemStatusResponse,
    UnknownValue,
    WsServerMessage,
)
from hassette_wire.lenient import _LENIENT_KEY, LenientValue, vocabulary_of
from open_alias_helpers import is_open_alias, open_aliases, plain_type
from pydantic import BaseModel, TypeAdapter, ValidationError

# Closed vocabularies stay strict on response models: adding a value to either is a breaking wire
# change, not version skew.
CLOSED_VOCABULARIES = (SourceTier, LogLevel)

# Request models stay strict (they carry no vocabulary fields today); a new one must be added here.
REQUEST_MODELS = {LogLevelRequest, SessionRequest}

OPEN_ALIASES = open_aliases()


def problem_body(code: Any) -> dict[str, Any]:
    return {"title": "Conflict", "status": 409, "detail": "d", "code": code}


def manifest_body(status: str, instance_status: str = "running") -> dict[str, Any]:
    return {
        "app_key": "a",
        "class_name": "A",
        "display_name": "A",
        "filename": "a.py",
        "enabled": True,
        "auto_loaded": False,
        "status": status,
        "instances": [{"app_key": "a", "index": 0, "instance_name": "a", "class_name": "A", "status": instance_status}],
    }


def test_unknown_problem_code_parses_leniently_and_keeps_raw_value() -> None:
    detail = ProblemDetail.model_validate(problem_body("rate_limited"), context=LENIENT_CONTEXT)

    assert isinstance(detail.code, UnknownValue)
    assert detail.code == "rate_limited"
    assert repr(detail.code) == "UnknownValue('rate_limited')"
    assert detail.code.value == "rate_limited"
    assert type(detail.code.value) is str


def test_known_value_still_parses_to_enum_member_under_lenient_context() -> None:
    detail = ProblemDetail.model_validate(problem_body("app_blocked"), context=LENIENT_CONTEXT)

    assert detail.code is ProblemCode.APP_BLOCKED


def test_unknown_values_in_list_json_and_nested_models() -> None:
    body = json.dumps([manifest_body("paused", instance_status="hibernating"), manifest_body("running")])

    parsed = TypeAdapter(list[AppSummary]).validate_json(body, context=LENIENT_CONTEXT)

    assert parsed[0].status == UnknownValue("paused")
    assert isinstance(parsed[0].instances[0].status, UnknownValue)
    assert parsed[1].status is AppStatus.RUNNING
    assert parsed[1].instances[0].status is ResourceStatus.RUNNING


def test_unknown_value_in_optional_open_field() -> None:
    data = {"app_key": "a", "index": 0, "status": "running", "previous_status": "hibernating"}

    parsed = AppStatusChangedData.model_validate(data, context=LENIENT_CONTEXT)

    assert parsed.previous_status == UnknownValue("hibernating")
    assert isinstance(parsed.previous_status, UnknownValue)
    absent = AppStatusChangedData.model_validate({**data, "previous_status": None}, context=LENIENT_CONTEXT)
    assert absent.previous_status is None


def test_unknown_values_in_ws_payload() -> None:
    message = {
        "type": "execution_completed",
        "timestamp": 1.0,
        "data": [{"kind": "workflow", "app_key": "a", "instance_index": 0, "status": "deferred", "duration_ms": 1.0}],
    }

    parsed = TypeAdapter(WsServerMessage).validate_python(message, context=LENIENT_CONTEXT)

    assert isinstance(parsed.data, list)
    assert parsed.data[0].kind == UnknownValue("workflow")
    assert isinstance(parsed.data[0].status, UnknownValue)


def test_unknown_literal_value_parses_leniently() -> None:
    status = {"status": "rebooting", "websocket_connected": True, "bootstrap_released": True}
    status |= {"uptime_seconds": 1.0, "entity_count": 0, "app_count": 0}

    parsed = SystemStatusResponse.model_validate(status, context=LENIENT_CONTEXT)

    assert isinstance(parsed.status, UnknownValue)


@pytest.mark.parametrize("context", [None, {}, [_LENIENT_KEY], {_LENIENT_KEY: 1}])
def test_anything_but_the_exact_context_flag_is_strict(context: Any) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProblemDetail.model_validate(problem_body("rate_limited"), context=context)

    assert exc_info.value.errors()[0]["type"] == "enum"


def test_lenient_context_survives_deepcopy_and_pickle() -> None:
    for context in (copy.deepcopy(LENIENT_CONTEXT), pickle.loads(pickle.dumps(LENIENT_CONTEXT))):  # noqa: S301
        detail = ProblemDetail.model_validate(problem_body("rate_limited"), context=context)

        assert isinstance(detail.code, UnknownValue)


def test_lenient_context_merges_with_other_keys() -> None:
    detail = ProblemDetail.model_validate(problem_body("rate_limited"), context={**LENIENT_CONTEXT, "other": 1})

    assert isinstance(detail.code, UnknownValue)


def test_strict_errors_are_pydantics_native_ones() -> None:
    with pytest.raises(ValidationError) as enum_exc:
        ProblemDetail.model_validate(problem_body("rate_limited"))
    with pytest.raises(ValidationError) as literal_exc:
        BlockingHandlerRef.model_validate(
            {"kind": "task", "id": 1, "name": "n", "handler_method": "m", "instance_index": 0}
        )

    assert enum_exc.value.errors()[0]["type"] == "enum"
    assert "Input should be 'invalid_app_key'" in enum_exc.value.errors()[0]["msg"]
    assert literal_exc.value.errors()[0]["type"] == "literal_error"


def test_strict_validation_rejects_an_unknown_value_outside_the_vocabulary() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProblemDetail.model_validate(problem_body(UnknownValue("rate_limited")))

    assert exc_info.value.errors()[0]["type"] == "enum"


@pytest.mark.parametrize("value", [5, {"code": "x"}, ["x"], None])
def test_non_string_input_still_raises_under_lenient_context(value: Any) -> None:
    with pytest.raises(ValidationError):
        ProblemDetail.model_validate(problem_body(value), context=LENIENT_CONTEXT)


def test_known_value_rejected_by_strict_mode_is_not_unknown() -> None:
    adapter = TypeAdapter(ProblemDetail)

    with pytest.raises(ValidationError):
        adapter.validate_python(problem_body("app_blocked"), strict=True, context=LENIENT_CONTEXT)


def test_unknown_value_that_a_newer_vocabulary_knows_revalidates_to_the_member() -> None:
    detail = ProblemDetail.model_validate(problem_body(UnknownValue("app_blocked")), context=LENIENT_CONTEXT)

    assert detail.code is ProblemCode.APP_BLOCKED


@pytest.mark.parametrize("alias", list(OPEN_ALIASES.values()), ids=list(OPEN_ALIASES))
@pytest.mark.parametrize("context", [None, LENIENT_CONTEXT], ids=["strict", "lenient"])
def test_in_vocabulary_str_subclasses_validate_to_the_known_value(alias: Any, context: Any) -> None:
    known = sorted(vocabulary_of(plain_type(alias)))[0]  # any known value works; sorted for stable ids
    foreign_member = StrEnum("Foreign", {"VALUE": known}).VALUE
    adapter = TypeAdapter(alias)

    for value in (UnknownValue(known), foreign_member):
        parsed = adapter.validate_python(value, context=context)

        assert parsed == known
        assert not isinstance(parsed, UnknownValue)
        assert type(parsed) is not type(value)


def test_str_mixin_enum_member_validates_by_value() -> None:
    mixin = Enum("Mixin", {"RUNNING": "running", "PAUSED": "paused"}, type=str)

    known = AppSummary.model_validate(manifest_body(mixin.RUNNING), context=LENIENT_CONTEXT)
    unknown = AppSummary.model_validate(manifest_body(mixin.PAUSED), context=LENIENT_CONTEXT)

    assert known.status is AppStatus.RUNNING
    assert unknown.status == UnknownValue("paused")


def test_member_of_another_enum_validates_by_value() -> None:
    known = AppSummary.model_validate(manifest_body(ResourceStatus.RUNNING), context=LENIENT_CONTEXT)
    unknown = AppSummary.model_validate(manifest_body(ResourceStatus.CRASHED), context=LENIENT_CONTEXT)

    assert known.status is AppStatus.RUNNING
    assert type(unknown.status) is UnknownValue
    assert unknown.status == "crashed"
    with pytest.raises(ValidationError):
        AppSummary.model_validate(manifest_body(ResourceStatus.CRASHED))


def test_json_dump_writes_raw_value_and_lenient_reparse_is_lossless() -> None:
    parsed = AppSummary.model_validate(manifest_body("paused", "running"), context=LENIENT_CONTEXT)

    dumped = parsed.model_dump_json()
    reparsed = AppSummary.model_validate_json(dumped, context=LENIENT_CONTEXT)

    assert json.loads(dumped)["status"] == "paused"
    assert json.loads(dumped)["instances"][0]["status"] == "running"
    assert reparsed == parsed
    assert isinstance(reparsed.status, UnknownValue)


def test_python_dump_returns_values_unchanged_without_warnings() -> None:
    parsed = AppSummary.model_validate(manifest_body("paused", "running"), context=LENIENT_CONTEXT)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dumped = parsed.model_dump()
        parsed.model_dump_json()

    assert type(dumped["status"]) is UnknownValue
    assert dumped["instances"][0]["status"] is ResourceStatus.RUNNING


@pytest.mark.parametrize("mode", ["json", "python"])
def test_dumping_an_out_of_vocabulary_str_that_bypassed_validation_still_warns(mode: str) -> None:
    bypassed = ServiceInfoResponse.model_construct(name="svc", status="bogus")

    with pytest.warns(UserWarning, match="Expected `enum`"):
        bypassed.model_dump(mode=mode)


def test_strict_python_dump_keeps_enum_members() -> None:
    listener = ListenerWithSummary.model_validate(
        {
            "listener_id": 1,
            "app_key": "a",
            "topic": "t",
            "handler_method": "m",
            "total_invocations": 0,
            "successful": 0,
            "failed": 0,
            "di_failures": 0,
            "cancelled": 0,
            "mode": "queued",
        }
    )

    assert listener.model_dump()["mode"] is ExecutionMode.QUEUED
    assert json.loads(listener.model_dump_json())["mode"] == "queued"


def test_lenient_instances_pass_into_strict_models_unrevalidated() -> None:
    """Pins pydantic's default revalidate_instances='never': strictness is a validation-time check only."""

    class Holder(BaseModel):
        manifest: AppSummary

    lenient = AppSummary.model_validate(manifest_body("paused"), context=LENIENT_CONTEXT)

    held = Holder(manifest=lenient)
    copied = lenient.model_copy(update={"status": UnknownValue("other")})

    assert isinstance(held.manifest.status, UnknownValue)
    assert copied.status == "other"


@pytest.mark.parametrize(
    "source",
    [
        str | UnknownValue,
        ResourceStatus,
        ResourceStatus | AppStatus,
        ResourceStatus | UnknownValue | None,
        Literal[1, 2] | UnknownValue,
    ],
)
def test_misshaped_alias_fails_at_schema_build(source: Any) -> None:
    with pytest.raises(TypeError, match="LenientValue"):
        TypeAdapter(Annotated[source, LenientValue("Bad")])


@pytest.mark.parametrize("alias", list(OPEN_ALIASES.values()), ids=list(OPEN_ALIASES))
@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_open_alias_keeps_the_plain_types_json_schema(alias: Any, mode: Any) -> None:
    plain = plain_type(alias)

    assert TypeAdapter(alias).json_schema(mode=mode) == TypeAdapter(plain).json_schema(mode=mode)


@pytest.mark.parametrize("name", sorted(OPEN_ALIASES))
def test_open_alias_marker_names_its_own_type(name: str) -> None:
    marker = next(meta for meta in OPEN_ALIASES[name].__metadata__ if isinstance(meta, LenientValue))

    assert f"Open{marker.type_name}" == name


def strict_vocabularies(annotation: Any) -> list[Any]:
    """Wire StrEnums and multi-value Literals reachable in ``annotation`` without passing through an open alias.

    Single-value Literals (WS ``type`` discriminators, ``"accepted"``) are constants, not vocabularies.
    """
    if is_open_alias(annotation):
        return []
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return [annotation]
    if get_origin(annotation) is Literal:
        is_closed = any(annotation == closed for closed in CLOSED_VOCABULARIES)
        is_multi_valued = len(get_args(annotation)) > 1
        return [annotation] if is_multi_valued and not is_closed else []
    # Unions, list[...], dict[...] and plain Annotated: check every argument.
    return [found for arg in get_args(annotation) for found in strict_vocabularies(arg)]


def test_every_response_vocabulary_field_is_open() -> None:
    """A response field typed with a wire enum or open Literal must use an Open<TypeName> alias."""
    models = [
        obj
        for obj in (getattr(hassette_wire, name) for name in hassette_wire.__all__)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj not in REQUEST_MODELS
    ]
    strict_fields = [
        f"{model.__name__}.{field_name}: {found}"
        for model in models
        for field_name, field in model.model_fields.items()
        # A bare Open<TypeName> field arrives with its Annotated unwrapped into field.metadata.
        if not any(isinstance(meta, LenientValue) for meta in field.metadata)
        for found in strict_vocabularies(field.annotation)
    ]

    # Sanity floor well under today's count, so a broken discovery filter fails instead of passing vacuously.
    assert len(models) >= 40, f"model discovery through __all__ found only {len(models)} response models"
    assert ProblemDetail in models
    assert not strict_fields, f"Response fields typed with a strict vocabulary: {strict_fields}"

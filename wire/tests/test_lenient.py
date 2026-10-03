import importlib
import json
import logging
import pkgutil
import uuid
import warnings
from enum import StrEnum
from typing import Annotated, Any, Literal, get_args, get_origin

import hassette_wire
import pytest
from hassette_wire import (
    LENIENT_CONTEXT,
    AppManifestResponse,
    BlockingHandlerRef,
    ExecutionMode,
    ListenerWithSummary,
    LogLevel,
    ManifestStatus,
    ProblemCode,
    ProblemDetail,
    ResourceStatus,
    SourceTier,
    SystemStatusResponse,
    UnknownValue,
    WsServerMessage,
)
from hassette_wire.lenient import LenientValue
from pydantic import BaseModel, TypeAdapter, ValidationError

# Vocabularies declared closed (D14): growing either is a breaking wire change, not version skew.
CLOSED_VOCABULARIES = (SourceTier, LogLevel)


def is_open_alias(obj: Any) -> bool:
    return get_origin(obj) is Annotated and any(isinstance(m, LenientValue) for m in obj.__metadata__)


def open_aliases() -> dict[str, Any]:
    """Every Open<TypeName> alias in any hassette_wire submodule, by name."""
    return {
        name: obj
        for module_info in pkgutil.iter_modules(hassette_wire.__path__)
        for name, obj in vars(importlib.import_module(f"hassette_wire.{module_info.name}")).items()
        if is_open_alias(obj)
    }


def problem(code: Any) -> dict[str, Any]:
    return {"title": "Conflict", "status": 409, "detail": "d", "code": code}


def manifest(status: str, instance_status: str = "running") -> dict[str, Any]:
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


def new_value() -> str:
    """A value no vocabulary contains, unique so the once-per-value warning fires for each test."""
    return f"new-{uuid.uuid4().hex[:8]}"


def test_unknown_problem_code_parses_leniently_and_keeps_raw_value() -> None:
    detail = ProblemDetail.model_validate(problem("rate_limited"), context=LENIENT_CONTEXT)

    assert isinstance(detail.code, UnknownValue)
    assert detail.code == "rate_limited"
    assert repr(detail.code) == "UnknownValue('rate_limited')"


def test_known_value_still_parses_to_enum_member_under_lenient_context() -> None:
    detail = ProblemDetail.model_validate(problem("app_blocked"), context=LENIENT_CONTEXT)

    assert detail.code is ProblemCode.APP_BLOCKED


def test_unknown_values_in_list_json_and_nested_models() -> None:
    body = json.dumps([manifest("paused", instance_status="hibernating"), manifest("running")])

    parsed = TypeAdapter(list[AppManifestResponse]).validate_json(body, context=LENIENT_CONTEXT)

    assert parsed[0].status == UnknownValue("paused")
    assert isinstance(parsed[0].instances[0].status, UnknownValue)
    assert parsed[1].status is ManifestStatus.RUNNING
    assert parsed[1].instances[0].status is ResourceStatus.RUNNING


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


@pytest.mark.parametrize("context", [None, {}, ["hassette_wire.lenient"], {"hassette_wire.lenient": 1}])
def test_anything_but_the_exact_context_flag_is_strict(context: Any) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProblemDetail.model_validate(problem("rate_limited"), context=context)

    assert exc_info.value.errors()[0]["type"] == "enum"


def test_lenient_context_merges_with_other_keys() -> None:
    detail = ProblemDetail.model_validate(problem("rate_limited"), context={**LENIENT_CONTEXT, "other": 1})

    assert isinstance(detail.code, UnknownValue)


def test_strict_errors_are_pydantics_native_ones() -> None:
    with pytest.raises(ValidationError) as enum_exc:
        ProblemDetail.model_validate(problem("rate_limited"))
    with pytest.raises(ValidationError) as literal_exc:
        BlockingHandlerRef.model_validate(
            {"kind": "task", "id": 1, "name": "n", "handler_method": "m", "instance_index": 0}
        )

    assert enum_exc.value.errors()[0]["type"] == "enum"
    assert "Input should be 'invalid_app_key'" in enum_exc.value.errors()[0]["msg"]
    assert literal_exc.value.errors()[0]["type"] == "literal_error"


def test_strict_validation_rejects_an_unknown_value_outside_the_vocabulary() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ProblemDetail.model_validate(problem(UnknownValue("rate_limited")))

    assert exc_info.value.errors()[0]["type"] == "enum"


@pytest.mark.parametrize("value", [5, {"code": "x"}, ["x"], None])
def test_non_string_input_still_raises_under_lenient_context(value: Any) -> None:
    with pytest.raises(ValidationError):
        ProblemDetail.model_validate(problem(value), context=LENIENT_CONTEXT)


def test_known_value_rejected_by_strict_mode_is_not_unknown() -> None:
    adapter = TypeAdapter(ProblemDetail)

    with pytest.raises(ValidationError):
        adapter.validate_python(problem("app_blocked"), strict=True, context=LENIENT_CONTEXT)


def test_unknown_value_that_a_newer_vocabulary_knows_revalidates_to_the_member() -> None:
    detail = ProblemDetail.model_validate(problem(UnknownValue("app_blocked")), context=LENIENT_CONTEXT)

    assert detail.code is ProblemCode.APP_BLOCKED


def test_member_of_another_enum_validates_by_value() -> None:
    known = AppManifestResponse.model_validate(manifest(ResourceStatus.RUNNING), context=LENIENT_CONTEXT)
    unknown = AppManifestResponse.model_validate(manifest(ResourceStatus.CRASHED), context=LENIENT_CONTEXT)

    assert known.status is ManifestStatus.RUNNING
    assert type(unknown.status) is UnknownValue
    assert unknown.status == "crashed"
    with pytest.raises(ValidationError):
        AppManifestResponse.model_validate(manifest(ResourceStatus.CRASHED))


def test_json_dump_writes_raw_value_and_lenient_reparse_is_lossless() -> None:
    parsed = AppManifestResponse.model_validate(manifest("paused", "running"), context=LENIENT_CONTEXT)

    dumped = parsed.model_dump_json()
    reparsed = AppManifestResponse.model_validate_json(dumped, context=LENIENT_CONTEXT)

    assert json.loads(dumped)["status"] == "paused"
    assert json.loads(dumped)["instances"][0]["status"] == "running"
    assert reparsed == parsed
    assert isinstance(reparsed.status, UnknownValue)


def test_python_dump_returns_values_unchanged_without_warnings() -> None:
    parsed = AppManifestResponse.model_validate(manifest("paused", "running"), context=LENIENT_CONTEXT)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dumped = parsed.model_dump()
        parsed.model_dump_json()

    assert type(dumped["status"]) is UnknownValue
    assert dumped["instances"][0]["status"] is ResourceStatus.RUNNING


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
        manifest: AppManifestResponse

    lenient = AppManifestResponse.model_validate(manifest("paused"), context=LENIENT_CONTEXT)

    held = Holder(manifest=lenient)
    copied = lenient.model_copy(update={"status": UnknownValue("other")})

    assert isinstance(held.manifest.status, UnknownValue)
    assert copied.status == "other"


def test_unknown_value_warns_once_per_type_and_value(caplog: pytest.LogCaptureFixture) -> None:
    value = new_value()

    with caplog.at_level(logging.WARNING, logger="hassette_wire.lenient"):
        for _ in range(3):
            ProblemDetail.model_validate(problem(value), context=LENIENT_CONTEXT)
        AppManifestResponse.model_validate(manifest(value), context=LENIENT_CONTEXT)

    messages = [r.getMessage() for r in caplog.records if value in r.getMessage()]
    assert len(messages) == 2
    assert "ProblemCode" in messages[0]
    assert "ManifestStatus" in messages[1]


@pytest.mark.parametrize(
    "source",
    [
        str | UnknownValue,
        ResourceStatus,
        ResourceStatus | ManifestStatus,
        ResourceStatus | UnknownValue | None,
        Literal[1, 2] | UnknownValue,
    ],
)
def test_misshaped_alias_fails_at_schema_build(source: Any) -> None:
    with pytest.raises(TypeError, match="LenientValue"):
        TypeAdapter(Annotated[source, LenientValue("Bad")])


@pytest.mark.parametrize("alias", list(open_aliases().values()), ids=list(open_aliases()))
@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_open_alias_keeps_the_plain_types_json_schema(alias: Any, mode: Any) -> None:
    plain = next(arm for arm in get_args(get_args(alias)[0]) if arm is not UnknownValue)

    assert TypeAdapter(alias).json_schema(mode=mode) == TypeAdapter(plain).json_schema(mode=mode)


def strict_vocabularies(tp: Any) -> list[Any]:
    """Wire StrEnums and multi-value Literals reachable in ``tp`` without passing through an open alias.

    Single-value Literals (WS ``type`` discriminators, ``"accepted"``) are constants, not vocabularies.
    """
    if is_open_alias(tp):
        return []
    if isinstance(tp, type) and issubclass(tp, StrEnum):
        return [tp]
    if get_origin(tp) is Literal:
        is_closed = any(tp == closed for closed in CLOSED_VOCABULARIES)
        return [tp] if len(get_args(tp)) > 1 and not is_closed else []
    # Unions, list[...], dict[...] and plain Annotated: check every argument.
    return [found for arg in get_args(tp) for found in strict_vocabularies(arg)]


def test_every_response_vocabulary_field_is_open() -> None:
    """A response field typed with a wire enum or open Literal must use an Open<TypeName> alias."""
    models = [
        obj
        for obj in (getattr(hassette_wire, name) for name in hassette_wire.__all__)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and not obj.__name__.endswith("Request")
    ]
    strict_fields = [
        f"{model.__name__}.{field_name}: {found}"
        for model in models
        for field_name, field in model.model_fields.items()
        # A bare Open<TypeName> field arrives with its Annotated unwrapped into field.metadata.
        if not any(isinstance(m, LenientValue) for m in field.metadata)
        for found in strict_vocabularies(field.annotation)
    ]

    assert len(models) > 40, "model discovery found too few response models"
    assert not strict_fields, f"Response fields typed with a strict vocabulary: {strict_fields}"

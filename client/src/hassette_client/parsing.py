"""Lenient parsing of hassette response bodies into ``hassette_wire`` types."""

from functools import cache
from typing import Any, TypeVar, overload

from hassette_wire import LENIENT_CONTEXT
from pydantic import TypeAdapter, ValidationError

from hassette_client.errors import ResponseValidationError

T = TypeVar("T")


@overload
def parse_response(response_type: type[T], payload: str | bytes, *, endpoint: str | None = None) -> T: ...


@overload
def parse_response(response_type: Any, payload: str | bytes, *, endpoint: str | None = None) -> Any: ...


def parse_response(response_type: Any, payload: str | bytes, *, endpoint: str | None = None) -> Any:
    """Parse a JSON response body into ``response_type`` the way :class:`~hassette_client.HassetteClient` does.

    Every client method parses through the same path, so this is a stable public entry point: a newer server's
    responses can be checked against this client release without making requests. Parsing is
    lenient (``hassette_wire.LENIENT_CONTEXT``): unknown fields are ignored, and an enum or
    ``Literal`` value this release doesn't know becomes a ``hassette_wire.UnknownValue``.

    Args:
        response_type: A ``hassette_wire`` model, or a type built from one, such as
            ``list[Execution]`` or ``Execution | None``.
        payload: The raw JSON body.
        endpoint: ``"<METHOD> <path>"`` the body came from, used in the error message.

    Raises:
        ResponseValidationError: The body isn't valid JSON or doesn't match ``response_type``. A list
            type fails as a whole when any one element doesn't match. Its ``status`` and
            ``content_type`` are ``None``, since there is no response.
    """
    return parse_payload(response_type, payload, endpoint=endpoint)


def parse_payload(
    response_type: Any,
    payload: str | bytes,
    *,
    endpoint: str | None = None,
    status: int | None = None,
    content_type: str | None = None,
) -> Any:
    """:func:`parse_response`, with the response's status and media type recorded on a failure."""
    try:
        return adapter_for(response_type).validate_json(payload, context=LENIENT_CONTEXT)
    except ValidationError as exc:
        # `from None`: the pydantic error's message quotes the offending input values, which come
        # from the server and must not reach logs through the exception chain.
        raise ResponseValidationError(
            model=type_name(response_type),
            endpoint=endpoint,
            problems=validation_problems(exc),
            status=status,
            content_type=content_type,
        ) from None


@cache
def adapter_for(response_type: Any) -> TypeAdapter[Any]:
    """Build each type's ``TypeAdapter`` once; building one compiles a validator, which is slow."""
    return TypeAdapter(response_type)


def type_name(response_type: Any) -> str:
    return response_type.__name__ if isinstance(response_type, type) else repr(response_type)


def validation_problems(exc: ValidationError) -> list[str]:
    """One ``"<location>: <error type>"`` per failure, leaving out the failing input."""
    return [f"{'.'.join(str(part) for part in error['loc']) or '<body>'}: {error['type']}" for error in exc.errors()]

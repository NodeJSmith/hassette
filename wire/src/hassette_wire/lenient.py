"""Opt-in lenient parsing of open-valued response fields.

A newer server can add a value to an enum or ``Literal`` that an older client doesn't know. Fields
typed with an ``Open<TypeName>`` alias accept such a value as an ``UnknownValue`` when, and only
when, the caller validates with ``context=LENIENT_CONTEXT``. Without that context they validate
exactly as the plain enum or ``Literal`` does, so the server's own construction and DB-row parsing
stay strict.
"""

import logging
import types
from collections.abc import Callable, Mapping
from enum import Enum, StrEnum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import GetCoreSchemaHandler, ValidationError
from pydantic_core import core_schema

LOGGER = logging.getLogger(__name__)

_LENIENT_KEY = "hassette_wire.lenient"

LENIENT_CONTEXT: Mapping[str, Any] = {_LENIENT_KEY: True}
"""Validation context that turns on lenient parsing of open-valued fields.

Pass it to any pydantic validation call: ``Model.model_validate_json(body, context=LENIENT_CONTEXT)``
or ``TypeAdapter(list[Model]).validate_python(data, context=LENIENT_CONTEXT)``. To combine it with
other context keys, merge it: ``{**LENIENT_CONTEXT, "other": ...}``. Any other context, including
``None``, validates strictly.

Each unknown value is logged only at DEBUG. Telling a user about version skew is the caller's job:
it knows the client and server versions, and can find unknowns with ``isinstance(v, UnknownValue)``.

Lenient-parsed objects are read-only client results. Don't pass them into server-side model
constructors: an already-built model instance isn't revalidated, so its ``UnknownValue`` fields
would slip past the strict check.
"""


class UnknownValue(str):
    """A value of an open-valued field that this version of ``hassette_wire`` doesn't recognize.

    Only produced under ``LENIENT_CONTEXT``. It is the raw string the server sent, so it compares,
    formats and serializes as that string, and a lenient re-parse by a newer client that knows the
    value yields the proper enum member or ``Literal`` value.

    Narrow with ``isinstance(v, UnknownValue)`` or ``case UnknownValue():``. Don't narrow with
    ``isinstance(v, str)``: a ``StrEnum`` member passes that check too. String methods
    (``v.upper()``, slicing) return a plain ``str``, and ``str(v)`` and f-strings show only the raw
    value, not that it was unknown. Like an enum member, it has ``.value``, which returns the raw value
    as a plain ``str``.

    Lenient-parsed objects are read-only client results: don't pass them into server-side model
    constructors (see ``LENIENT_CONTEXT``).
    """

    __slots__ = ()

    @property
    def value(self) -> str:
        """The raw value, as a plain ``str``."""
        return str(self)

    def __repr__(self) -> str:
        return f"UnknownValue({str.__repr__(self)})"


class LenientValue:
    """``Annotated`` marker that makes a ``<StrEnum or str Literal> | UnknownValue`` field open.

    The field validates as the enum or ``Literal`` arm alone, and keeps that arm's JSON schema. Under
    ``LENIENT_CONTEXT``, a ``str`` the arm rejects becomes an ``UnknownValue`` instead of an error.
    ``type_name`` names the open type in the unknown-value DEBUG log.
    """

    def __init__(self, type_name: str) -> None:
        self.type_name = type_name

    def __get_pydantic_core_schema__(self, source: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        arm = known_arm(source, self.type_name)
        arm_schema = handler.generate_schema(arm)
        return core_schema.with_info_wrap_validator_function(
            make_validator(self.type_name, vocabulary_of(arm)),
            arm_schema,
            # Wraps the arm's own serializer, in both modes, so only an UnknownValue skips it. Everything
            # else, including a str that bypassed validation, still gets the arm's "Expected `enum`" warning.
            serialization=core_schema.wrap_serializer_function_ser_schema(
                serialize_open_value, schema=arm_schema, when_used="always"
            ),
        )


def known_arm(source: Any, type_name: str) -> Any:
    """Return the enum or ``Literal`` arm of ``source``, raising ``TypeError`` unless ``source`` is exactly
    ``<StrEnum subclass or all-str Literal> | UnknownValue``.
    """
    shape_error = TypeError(
        f"LenientValue({type_name!r}) must annotate '<StrEnum subclass or str Literal> | UnknownValue', got {source!r}"
    )
    if get_origin(source) not in (Union, types.UnionType):
        raise shape_error
    args = get_args(source)
    if len(args) != 2 or UnknownValue not in args:
        raise shape_error
    arm = args[0] if args[1] is UnknownValue else args[1]
    if isinstance(arm, type) and issubclass(arm, StrEnum):
        return arm
    if get_origin(arm) is Literal and all(type(v) is str for v in get_args(arm)):
        return arm
    raise shape_error


def vocabulary_of(arm: Any) -> frozenset[str]:
    """The string values ``arm`` accepts: an enum's member values, or a ``Literal``'s arguments."""
    if isinstance(arm, type) and issubclass(arm, StrEnum):
        return frozenset(member.value for member in arm)
    return frozenset(get_args(arm))


def make_validator(type_name: str, vocabulary: frozenset[str]) -> Callable[..., Any]:
    def validate(
        value: Any, handler: core_schema.ValidatorFunctionWrapHandler, info: core_schema.ValidationInfo
    ) -> Any:
        try:
            return handler(value)
        except ValidationError:
            if not isinstance(value, str):
                raise
            raw = value.value if isinstance(value, Enum) else str(value)
            if raw in vocabulary:
                # A known value is never unknown, in either context. A plain str here was rejected by
                # strict=True python validation, so its error stands. A str subclass (UnknownValue, another
                # enum's member) can be rejected by a Literal on pydantic-core 2.18 (pydantic 2.7), which
                # refuses subclasses there, so retry it as the plain value.
                if type(value) is str:
                    raise
                return handler(raw)
            if not is_lenient(info.context):
                raise
            # DEBUG and stateless on purpose: a validator can't tell skew from a bad value or a parse
            # that fails later, so the user-facing message belongs to the consumer that knows the versions.
            LOGGER.debug("Parsed unrecognized %s value %r as UnknownValue (field %r)", type_name, raw, info.field_name)
            return UnknownValue(raw)

    return validate


def is_lenient(context: Any) -> bool:
    return isinstance(context, Mapping) and context.get(_LENIENT_KEY) is True


def serialize_open_value(value: Any, handler: core_schema.SerializerFunctionWrapHandler) -> Any:
    # An UnknownValue is returned as-is: python mode keeps the object, JSON mode infers a plain string.
    return value if isinstance(value, UnknownValue) else handler(value)

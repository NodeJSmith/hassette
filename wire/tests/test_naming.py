"""The mechanical half of the class-naming rule in the ``hassette_wire`` package docstring.

Pinned here: no export uses a retired suffix, the ``*WsMessage`` exports are exactly the members of
``WsServerMessage``, each is discriminated by a ``type`` Literal, and ``*Data`` is exactly the set of WS
payloads. Left to review (``REVIEW.md``): whether an HTTP body is a record (bare noun) or an envelope
(``*Response``/``*Request``), and collisions with public ``hassette`` names, which this package can't import.
"""

import types
import typing

import hassette_wire
import pytest
from pydantic import BaseModel

RETIRED_SUFFIXES = ("Payload", "WithSummary")

EXPORTED_MODELS = {
    name: obj
    for name in hassette_wire.__all__
    if isinstance(obj := getattr(hassette_wire, name), type) and issubclass(obj, BaseModel)
}

# WsServerMessage is Annotated[Union[...], Field(discriminator="type")].
WS_MESSAGE_UNION, _discriminator = typing.get_args(hassette_wire.WsServerMessage)
WS_MESSAGES: tuple[type[BaseModel], ...] = typing.get_args(WS_MESSAGE_UNION)

# A message with no payload (e.g. log_hint) has no `data` field and is exempt from the payload checks.
WS_MESSAGES_WITH_DATA = [m for m in WS_MESSAGES if "data" in m.model_fields]


def model_name(model: type[BaseModel]) -> str:
    return model.__name__


def payload_model(message: type[BaseModel]) -> type[BaseModel]:
    """The model a message's ``data`` field carries, unwrapping a single-argument alias such as ``list[...]``."""
    annotation = message.model_fields["data"].annotation
    if isinstance(annotation, types.GenericAlias):
        (annotation,) = typing.get_args(annotation)
    assert isinstance(annotation, type), f"unsupported data annotation on {message.__name__}: {annotation!r}"
    assert issubclass(annotation, BaseModel), f"data on {message.__name__} is not a model: {annotation!r}"
    return annotation


@pytest.mark.parametrize("name", sorted(EXPORTED_MODELS))
def test_no_export_uses_a_retired_suffix(name: str) -> None:
    assert not name.endswith(RETIRED_SUFFIXES)


def test_ws_message_exports_match_server_message_union_members() -> None:
    exported = {model for name, model in EXPORTED_MODELS.items() if name.endswith("WsMessage")}
    assert exported == set(WS_MESSAGES)


@pytest.mark.parametrize("message", WS_MESSAGES, ids=model_name)
def test_ws_message_is_named_ws_message_and_discriminated_by_literal_type(message: type[BaseModel]) -> None:
    assert message.__name__.endswith("WsMessage")
    assert typing.get_origin(message.model_fields["type"].annotation) is typing.Literal


@pytest.mark.parametrize("message", WS_MESSAGES_WITH_DATA, ids=model_name)
def test_ws_payload_ends_in_data(message: type[BaseModel]) -> None:
    assert payload_model(message).__name__.endswith("Data")


def test_every_data_export_is_a_ws_payload() -> None:
    data_exports = {model for name, model in EXPORTED_MODELS.items() if name.endswith("Data")}
    assert data_exports == {payload_model(m) for m in WS_MESSAGES_WITH_DATA}

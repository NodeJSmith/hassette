"""Integration tests for ``config_defaults`` on GET /api/config."""

from httpx2 import AsyncClient
from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined

from hassette.config import HassetteConfig

from .conftest import CONFIG_PATH, get_json


def expected_defaults(model: type[BaseModel]) -> dict[str, object]:
    """Build the expected ``config_defaults`` from a model's fields, independently of its JSON schema."""
    expected: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if field.default is not PydanticUndefined:
            expected[name] = TypeAdapter(field.annotation).dump_python(field.default, mode="json")
        elif isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            expected[name] = expected_defaults(field.annotation)
    return expected


async def test_config_defaults_match_model_defaults(client: AsyncClient) -> None:
    config_defaults = (await get_json(client, CONFIG_PATH))["config_defaults"]

    assert config_defaults == expected_defaults(HassetteConfig)
    assert "port" in config_defaults["web_api"]

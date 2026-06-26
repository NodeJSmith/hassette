"""Configuration endpoint."""

from fastapi import APIRouter

from hassette.config import HassetteConfig
from hassette.web.config_view import build_config_view
from hassette.web.dependencies import HassetteDep
from hassette.web.models import ConfigSchemaResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigSchemaResponse)
async def get_config(hassette: HassetteDep) -> ConfigSchemaResponse:
    """Return the complete Hassette configuration as a JSON schema plus current values.

    ``config_schema`` is the fully-inlined JSON schema derived from the
    ``HassetteConfig`` class (all ``$ref``/``$defs`` resolved server-side).
    ``config_values`` is the current configuration serialized to JSON with
    any ``SecretStr`` field replaced by a masked placeholder — the plaintext
    value is never sent over the wire.  Every field and nested group is present;
    nothing is omitted.
    """
    schema = HassetteConfig.model_json_schema()
    values = hassette.config.model_dump(mode="json")
    view = build_config_view(schema, values)
    return ConfigSchemaResponse(**view)

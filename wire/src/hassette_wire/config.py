from typing import Any

from pydantic import BaseModel


class ConfigSchemaResponse(BaseModel):
    """Complete Hassette configuration as a JSON schema plus current values.

    ``config_schema`` is the fully-inlined JSON schema (all ``$ref``/``$defs`` resolved)
    derived from ``HassetteConfig.model_json_schema()``.  ``config_values`` is the current
    configuration serialized to JSON with ``SecretStr`` fields replaced by a masked
    placeholder.  Every field and nested group is present — nothing is omitted.
    """

    config_schema: dict[str, Any]
    config_values: dict[str, Any]

from typing import Any

from pydantic import BaseModel, Field


class ConfigSchemaResponse(BaseModel):
    """Complete Hassette configuration as a JSON schema plus current values.

    ``config_schema`` is the fully-inlined JSON schema (all ``$ref``/``$defs`` resolved)
    derived from ``HassetteConfig.model_json_schema()``.  ``config_values`` is the current
    configuration serialized to JSON with ``SecretStr`` fields replaced by a masked
    placeholder.  Every field and nested group is present — nothing is omitted.
    ``config_defaults`` mirrors the shape of ``config_values`` and holds each field's schema
    default; a field with no schema default (including ``default_factory`` fields) is omitted.
    """

    config_schema: dict[str, Any]
    config_values: dict[str, Any]
    config_defaults: dict[str, Any] = Field(default_factory=dict)

"""Configuration endpoint."""

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from hassette.config import HassetteConfig
from hassette.web.config_view import build_config_view, mask_app_config, resolve_app_config_cls
from hassette.web.dependencies import HassetteDep
from hassette.web.models import ConfigSchemaResponse

if TYPE_CHECKING:
    from hassette import Hassette

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
    view["config_values"] = _mask_manifest_configs(hassette, view["config_values"])
    return ConfigSchemaResponse(**view)


def _mask_manifest_configs(hassette: "Hassette", config_values: dict[str, Any]) -> dict[str, Any]:
    """Mask ``app_config`` inside each manifest so secrets never leak via the global endpoint.

    ``HassetteConfig`` types ``app_config`` as ``dict[str, Any]``, so the schema-driven
    masking in ``build_config_view`` has no ``writeOnly``/``format: password`` markers to
    act on.  This post-processing step resolves each app's real config class via
    ``resolve_app_config_cls`` and re-masks with the type-accurate schema.  When no schema
    is available, every string value is masked as a safe floor.
    """
    manifests = config_values.get("apps", {}).get("manifests")
    if not manifests:
        return config_values

    masked_manifests = {}
    for app_key, manifest_dict in manifests.items():
        raw_config = manifest_dict.get("app_config")
        if raw_config is None:
            masked_manifests[app_key] = manifest_dict
            continue
        config_cls = resolve_app_config_cls(hassette, app_key)
        masked_manifests[app_key] = {**manifest_dict, "app_config": mask_app_config(config_cls, raw_config)}

    return {**config_values, "apps": {**config_values["apps"], "manifests": masked_manifests}}

"""Shared view builder for config endpoints: schema deref and type-driven value masking.

The global config endpoint calls ``build_config_view`` to produce a
``{config_schema, config_values}`` pair. The per-app endpoint calls ``deref_schema`` and
``mask_values`` directly so a multi-instance config derefs its schema once and masks each
instance against it. Both paths produce a pair where:

- ``config_schema`` is the JSON schema with all ``$ref``/``$defs`` resolved inline so the
  frontend never needs to walk a reference.
- ``config_values`` is the values dict with any field marked ``writeOnly: true`` or
  ``format: "password"`` (i.e. ``SecretStr``-typed) replaced by ``MASK_SENTINEL`` when
  set, and left ``None``/absent when unset.

Masking is type-driven — it reads the schema markers, not the field names.

Note: ``jsonref`` can mangle discriminator ``mapping`` refs under discriminated unions.
This is not an issue for the current plain nested-model config groups, but re-check if
any config field ever becomes a discriminated union.

Note: the OpenAPI freshness check does not cover ``ui`` annotation content (it rides in a
``dict[str, Any]`` field), so the ``ui``-metadata-shape unit test is the sole guard against
``ui``-shape drift.
"""

from logging import getLogger
from typing import TYPE_CHECKING, Any

import jsonref

from hassette.app.app_config import AppConfig
from hassette.utils.app_utils import class_already_loaded, get_loaded_class

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest

MASK_SENTINEL = "••••••••"
"""Placeholder shown in the UI when a secret field is set but not revealed."""


def _is_secret_node(node: dict[str, Any]) -> bool:
    """Return True when a schema property node represents a secret-typed field.

    Checks for ``writeOnly: true`` or ``format: "password"`` directly on the node,
    and also inside any ``anyOf`` branch — covering the ``SecretStr | None`` pattern
    where Pydantic emits ``anyOf: [{writeOnly: true, format: password, ...}, {type: null}]``.
    """
    if node.get("writeOnly") is True or node.get("format") == "password":
        return True
    for branch in node.get("anyOf", []):
        if isinstance(branch, dict) and (branch.get("writeOnly") is True or branch.get("format") == "password"):
            return True
    return False


def _object_properties(node: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``properties`` dict of an object-typed schema node, or None.

    Handles a required nested model (``{type: object, properties: {...}}``) directly,
    and an optional nested model (``SomeGroup | None``) which Pydantic emits as
    ``anyOf: [{type: object, properties: {...}}, {type: null}]`` — without the anyOf
    branch, secrets inside an optional nested group would pass through unmasked.
    """
    if node.get("type") == "object" and "properties" in node:
        return node["properties"]
    for branch in node.get("anyOf", []):
        if isinstance(branch, dict) and branch.get("type") == "object" and "properties" in branch:
            return branch["properties"]
    return None


def mask_values(schema_props: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``values`` with secret fields replaced by ``MASK_SENTINEL``.

    Walks ``schema_props`` (the ``properties`` dict of a deref'd schema node).
    For each property:
    - If the node is a secret (``writeOnly``/``format: password``), replaces the value
      with ``MASK_SENTINEL`` when present and non-empty, leaves it ``None``/absent otherwise.
    - If the node is a nested object with its own ``properties`` (required or optional via
      ``anyOf``), recurses so secrets at any depth are masked.

    Does not mutate the input dict; returns a new dict.
    """
    result = dict(values)
    for key, node in schema_props.items():
        if key not in result:
            continue
        if _is_secret_node(node):
            current = result[key]
            if current is not None and current != "":
                result[key] = MASK_SENTINEL
            continue
        nested_props = _object_properties(node)
        if nested_props is not None and isinstance(result.get(key), dict):
            result[key] = mask_values(nested_props, result[key])
    return result


def _materialize(obj: Any, seen: frozenset[int] | None = None) -> Any:
    """Convert ``jsonref`` proxy objects to plain Python dicts/lists.

    ``jsonref.replace_refs()`` returns lazy proxy objects that behave like the underlying
    value but are not concrete Python dicts/lists. FastAPI's serializer must receive plain
    objects, and ``json.dumps`` would fail on proxy types.

    Cycles are broken by tracking object ids. When the same object is seen again during
    recursion, an empty dict is returned in its place — this terminates self-referential
    schemas without infinite recursion.
    """
    if seen is None:
        seen = frozenset()
    obj_id = id(obj)
    if obj_id in seen:
        return {}
    if isinstance(obj, dict):
        new_seen = seen | {obj_id}
        return {k: _materialize(v, new_seen) for k, v in obj.items()}
    if isinstance(obj, list):
        new_seen = seen | {obj_id}
        return [_materialize(v, new_seen) for v in obj]
    return obj


def _mask_leaf(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _mask_leaf(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_leaf(v) for v in value]
    if isinstance(value, str) and value != "":
        return MASK_SENTINEL
    return value


def mask_all_values(values: dict[str, Any]) -> dict[str, Any]:
    """Mask every non-empty string leaf — the safe floor when no schema is available.

    Type-driven masking needs the field's schema to tell a secret from a plain value.
    When that schema cannot be obtained (the app class is not loaded), there is no way
    to know which fields are secret, so every string value is masked rather than risk
    leaking one. Keys and structure are preserved; non-string scalars (bools, numbers,
    null) and empty strings are left visible since they can never be a secret.
    """
    return {k: _mask_leaf(v) for k, v in values.items()}


def deref_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve every ``$ref``/``$defs`` in a JSON schema inline and return a plain dict.

    ``jsonref.replace_refs`` returns lazy proxy objects; ``_materialize`` converts them to
    concrete dicts/lists so FastAPI and ``json.dumps`` can serialize them. The ``$defs``
    store is dropped because every reference is now inlined.

    Split out of ``build_config_view`` so the multi-instance app path can deref a schema
    once and reuse it across instances, rather than re-running the deref per instance.
    """
    plain_schema = _materialize(jsonref.replace_refs(schema))
    if not isinstance(plain_schema, dict):
        return {}
    plain_schema.pop("$defs", None)
    return plain_schema


def build_config_view(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Build the unified config view payload from a JSON schema and a values dict.

    Args:
        schema: A Pydantic ``model_json_schema()`` dict (may contain ``$ref``/``$defs``).
        values: The current config values — either ``model_dump(mode="json")`` output or
            a raw TOML dict. For the global endpoint, Pydantic already masks ``SecretStr``
            fields natively; this function's schema-driven mask is then idempotent over it
            (both paths end up with ``MASK_SENTINEL``).

    Returns:
        ``{"config_schema": <deref'd, materialized>, "config_values": <masked>}``

        ``config_schema`` contains no ``$ref`` or ``$defs`` — all references are inlined.
        ``config_values`` has any field marked ``writeOnly: true`` or ``format: "password"``
        replaced with ``MASK_SENTINEL`` when set, left ``None``/absent when unset.
    """
    plain_schema = deref_schema(schema)
    masked_values = mask_values(plain_schema.get("properties", {}), values)
    return {"config_schema": plain_schema, "config_values": masked_values}


def resolve_app_config_cls(
    hassette: "Hassette", app_key: str, manifest: "AppManifest | None" = None
) -> type[AppConfig] | None:
    """Resolve an app's ``AppConfig`` class from the running instance or the loaded module.

    Returns ``None`` when the app has no running instance and its class is not already
    loaded (e.g. a disabled app that never started).  Does not import the app module — a
    config request must not trigger loading of arbitrary app code on the unauthenticated API.
    """
    instance = hassette.app_handler.registry.get(app_key)
    if instance is not None:
        return getattr(type(instance), "app_config_cls", None)
    if manifest is None:
        manifest = hassette.config.apps.manifests.get(app_key)
    if manifest is not None and class_already_loaded(manifest.full_path, manifest.class_name):
        return get_loaded_class(manifest.full_path, manifest.class_name).app_config_cls
    return None


def mask_app_config(
    config_cls: type[AppConfig] | None,
    app_config: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | list[dict[str, Any]]:
    """Mask an app's config values using its real schema when available, else mask all strings.

    When ``config_cls`` is provided, uses schema-driven masking (only fields marked
    ``writeOnly``/``format: password``, i.e. ``SecretStr``-typed, are masked).  When
    ``None`` or schema generation fails, every string value is masked as a safe floor.
    """
    if config_cls is not None:
        try:
            schema_props = deref_schema(config_cls.model_json_schema()).get("properties", {})
            if isinstance(app_config, list):
                return [mask_values(schema_props, inst) for inst in app_config]
            return mask_values(schema_props, app_config)
        except Exception:
            LOGGER.warning("Schema generation failed for %s; falling back to safe-floor masking", config_cls)
    if isinstance(app_config, list):
        return [mask_all_values(inst) for inst in app_config]
    return mask_all_values(app_config)

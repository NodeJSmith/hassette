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

import re
from collections.abc import Iterator
from logging import getLogger
from typing import TYPE_CHECKING, Any

import jsonref

from hassette.app.app_config import AppConfig
from hassette.utils.app_utils import class_already_loaded, get_loaded_class

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.config.classes import AppManifest

LOGGER = getLogger(__name__)

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


def _shape_candidates(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield ``node`` itself, then any ``anyOf``/``oneOf``/``allOf`` branch.

    An optional field wraps its real shape in a union — ``SomeGroup | None`` becomes
    ``anyOf: [{type: object, properties: {...}}, {type: null}]`` and
    ``tuple[SecretStr, SecretStr] | None`` becomes ``anyOf: [{type: array, prefixItems:
    [...]}, {type: null}]``. Object and container shapes therefore have to be looked for in
    the branches as well as on the node, or secrets nested inside an optional group or
    container pass through unmasked.

    ``anyOf`` is what optional fields actually emit today. ``oneOf`` is what a discriminated
    union would emit, which the module docstring already flags as a shape to expect. ``allOf``
    is not emitted by the current Pydantic — a ``$ref`` with sibling keywords is inlined
    rather than wrapped — but older versions did wrap, and looking in one extra place can only
    ever mask more, never less, so it stays as fail-safe insurance on a security boundary.
    """
    yield node
    for keyword in ("anyOf", "oneOf", "allOf"):
        for branch in node.get(keyword, []):
            if isinstance(branch, dict):
                yield branch


def _mask_object(shape: dict[str, Any], value: dict[str, Any]) -> dict[str, Any] | None:
    """Mask a mapping value against an object-shaped schema node, or None if it is not one.

    Three keys can describe a mapping's values, in descending specificity: ``properties``
    names exact keys, ``patternProperties`` matches keys by regex (which is what Pydantic
    emits for a mapping whose key type carries a pattern constraint), and
    ``additionalProperties`` covers everything left. A model with ``extra="allow"`` can carry
    more than one, so each key is resolved against the most specific match rather than
    picking a single schema key and ignoring the others.
    """
    named_props = shape.get("properties")
    pattern_props = shape.get("patternProperties")
    extra_props = shape.get("additionalProperties")
    if not any(isinstance(candidate, dict) for candidate in (named_props, pattern_props, extra_props)):
        return None
    named_props = named_props if isinstance(named_props, dict) else {}
    pattern_props = pattern_props if isinstance(pattern_props, dict) else {}

    masked: dict[str, Any] = {}
    for key, item in value.items():
        if key in named_props:
            masked[key] = _mask_node(named_props[key], item)
            continue

        # JSON Schema applies every patternProperties entry whose regex matches (unanchored),
        # so all matches are folded in rather than stopping at the first.
        matched_pattern = False
        item_masked = item
        for pattern, sub_node in pattern_props.items():
            if isinstance(sub_node, dict) and re.search(pattern, key):
                item_masked = _mask_node(sub_node, item_masked)
                matched_pattern = True

        if matched_pattern:
            masked[key] = item_masked
        elif isinstance(extra_props, dict):
            masked[key] = _mask_node(extra_props, item)
        else:
            masked[key] = item
    return masked


def _mask_array(shape: dict[str, Any], value: list[Any]) -> list[Any] | None:
    """Mask a list value against an array-shaped schema node, or None if it is not one.

    ``prefixItems`` is positional and describes a fixed-length tuple; ``items`` is homogeneous
    and describes the rest. A tuple emits only the former and a list only the latter, so both
    are handled, with positional slots taking precedence.
    """
    prefix_items = shape.get("prefixItems")
    item_schema = shape.get("items")
    if not isinstance(prefix_items, list) and not isinstance(item_schema, dict):
        return None
    prefix_items = prefix_items if isinstance(prefix_items, list) else []

    masked: list[Any] = []
    for index, item in enumerate(value):
        if index < len(prefix_items) and isinstance(prefix_items[index], dict):
            masked.append(_mask_node(prefix_items[index], item))
        elif isinstance(item_schema, dict):
            masked.append(_mask_node(item_schema, item))
        else:
            masked.append(item)
    return masked


def _mask_node(node: dict[str, Any], value: Any) -> Any:
    """Return ``value`` masked according to the schema node describing it.

    The walk is schema-and-value recursive rather than property recursive: an object's
    ``properties``/``additionalProperties`` and a container's ``prefixItems``/``items`` are
    all descended, and each descent lands back here — so an object inside a list, or a list
    inside a mapping, is reached the same way a top-level field is.

    Returns new dicts and lists; never mutates ``value``.
    """
    if _is_secret_node(node):
        return MASK_SENTINEL if value is not None and value != "" else value

    # A tuple is what prefixItems exists to describe, so it is masked like a list and handed
    # back as a tuple. Neither endpoint produces one today -- TOML parsing and
    # model_dump(mode="json") both yield lists -- but passing one through unmasked would be a
    # silent leak rather than a visible failure.
    if isinstance(value, tuple):
        masked_items = _mask_node(node, list(value))
        return tuple(masked_items) if isinstance(masked_items, list) else masked_items

    # A plain scalar has nothing to descend into, whatever the schema says about it.
    if not isinstance(value, dict | list):
        return value

    # Every candidate shape is applied in turn rather than stopping at the first that matches.
    # A union can offer several branches that all describe an object, and picking one means a
    # branch that is not chosen never masks: for a discriminated union, a variant's secret key
    # is simply absent from the other variant's properties and passes straight through. Folding
    # is safe because masking only ever replaces a value with the sentinel or recurses -- it
    # never restores plaintext, and re-masking the sentinel is a no-op -- so applying a branch
    # that does not describe this value cannot mask anything extra.
    masked = value
    for shape in _shape_candidates(node):
        result = _mask_object(shape, masked) if isinstance(masked, dict) else _mask_array(shape, masked)
        if result is not None:
            masked = result
    return masked


def mask_values(schema_props: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``values`` with secret fields replaced by ``MASK_SENTINEL``.

    Walks ``schema_props`` (the ``properties`` dict of a deref'd schema node) and masks each
    value against its own node. A secret (``writeOnly``/``format: password``) is replaced
    with ``MASK_SENTINEL`` when present and non-empty, and left ``None``/empty/absent
    otherwise. Nested objects and list/tuple/mapping containers are descended, so a secret
    is reached at any depth and through any combination of the two.

    Keys absent from ``schema_props``, and plain non-secret values, are passed through
    untouched — masking is type-driven, so an ordinary list or mapping stays readable.

    Does not mutate the input dict; returns a new dict.
    """
    return {
        key: _mask_node(schema_props[key], value) if key in schema_props else value for key, value in values.items()
    }


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
    loaded (e.g. a disabled app that never started). Does not import the app module — a
    config request must not trigger loading of arbitrary app code on the unauthenticated API.
    """
    instance = hassette.app_handler.registry.get(app_key)
    if instance is not None:
        return getattr(type(instance), "app_config_cls", None)
    if manifest is None:
        manifest = hassette.config.apps.manifests.get(app_key)
    if manifest is not None and class_already_loaded(manifest.full_path, manifest.class_name):
        return getattr(get_loaded_class(manifest.full_path, manifest.class_name), "app_config_cls", None)
    return None


def mask_app_config(
    app_config_cls: type[AppConfig] | None,
    app_config: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any] | list[dict[str, Any]]:
    """Mask an app's config values using its real schema when available, else mask all strings.

    When ``app_config_cls`` is provided, uses schema-driven masking (only fields marked
    ``writeOnly``/``format: password``, i.e. ``SecretStr``-typed, are masked). When
    ``None`` or schema generation fails, every string value is masked as a safe floor.
    """
    if app_config_cls is not None:
        try:
            schema_props = deref_schema(app_config_cls.model_json_schema()).get("properties", {})
            if isinstance(app_config, list):
                return [mask_values(schema_props, inst) for inst in app_config]
            return mask_values(schema_props, app_config)
        except Exception:
            LOGGER.warning(
                "Schema generation failed for %s; falling back to safe-floor masking", app_config_cls, exc_info=True
            )
    if isinstance(app_config, list):
        return [mask_all_values(inst) for inst in app_config]
    return mask_all_values(app_config)

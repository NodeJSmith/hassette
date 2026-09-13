"""Extract service definitions from services.yaml + AST hybrid."""

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

_KEY_REF = re.compile(r"^\[%key:(.+?)%\]$")
_MAX_KEY_REF_DEPTH = 6  # bounds recursion through chained [%key:...%] references

SupportsResponseValue = Literal["NONE", "OPTIONAL", "ONLY"]
_VALID_SUPPORTS_RESPONSE: set[str] = {"NONE", "OPTIONAL", "ONLY"}


@dataclass
class ServiceField:
    name: str
    selector_type: str
    selector_data: dict
    required: bool = False
    description: str | None = None


@dataclass
class ExtractedService:
    name: str
    method_name: str
    fields: list[ServiceField] = field(default_factory=list)
    required_features: list[str] = field(default_factory=list)
    description: str | None = None
    supports_response: SupportsResponseValue = "NONE"


def extract_services(component_dir: Path) -> list[ExtractedService]:
    """Extract service definitions from a domain's services.yaml + __init__.py."""
    services_yaml = component_dir / "services.yaml"
    if not services_yaml.exists():
        return []

    try:
        raw = yaml.safe_load(services_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        print(f"WARNING: Failed to parse {services_yaml}", file=sys.stderr)
        return []

    if not raw or not isinstance(raw, dict):
        return []

    registrations = _extract_service_registrations(component_dir / "__init__.py")
    service_descs, field_descs = _extract_descriptions(component_dir)

    services: list[ExtractedService] = []
    for service_name, service_def in raw.items():
        if not isinstance(service_def, dict):
            continue
        if service_name.startswith("."):
            continue

        fields = _extract_fields(service_def, field_descs.get(service_name, {}))
        # method_name: exact lookup only, preserving the old behavior (callers may rely on the
        # literal AST key). supports_response: fuzzy lookup, because HA registers services under
        # unresolved constants (SERVICE_BROWSE_MEDIA) or enum members (TodoServices.GET_ITEMS)
        # that don't match the yaml key without normalization.
        direct_reg = registrations.get(service_name)
        method_name = direct_reg.method_name if direct_reg and direct_reg.method_name else service_name
        fuzzy_reg = _find_registration(service_name, registrations)
        supports_response = fuzzy_reg.supports_response if fuzzy_reg else "NONE"

        services.append(
            ExtractedService(
                name=service_name,
                method_name=method_name,
                fields=fields,
                description=service_descs.get(service_name),
                supports_response=supports_response,
            )
        )

    return services


def _extract_fields(service_def: dict, descriptions: dict[str, str]) -> list[ServiceField]:
    """Extract fields from a service definition, flattening sections."""
    fields: list[ServiceField] = []
    raw_fields = service_def.get("fields", {})

    if not isinstance(raw_fields, dict):
        return fields

    for field_name, field_def in raw_fields.items():
        if not isinstance(field_def, dict):
            continue

        if "fields" in field_def and "selector" not in field_def:
            nested = field_def["fields"]
            if isinstance(nested, dict):
                for sub_name, sub_def in nested.items():
                    if isinstance(sub_def, dict):
                        fields.append(_parse_field(sub_name, sub_def, descriptions.get(sub_name)))
        else:
            fields.append(_parse_field(field_name, field_def, descriptions.get(field_name)))

    return fields


def _parse_field(name: str, field_def: dict, description: str | None) -> ServiceField:
    """Parse a single service field definition."""
    required = field_def.get("required", False)
    selector = field_def.get("selector", {})

    if isinstance(selector, dict) and selector:
        selector_type = next(iter(selector))
        selector_data = selector.get(selector_type, {}) or {}
    else:
        selector_type = "text"
        selector_data = {}

    return ServiceField(
        name=name,
        selector_type=selector_type,
        selector_data=selector_data if isinstance(selector_data, dict) else {},
        required=bool(required),
        description=description,
    )


def _extract_descriptions(component_dir: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Read the domain's strings.json once for service- and field-level descriptions.

    Returns ``(service_name -> service description, service_name -> {field_name -> description})``.
    Home Assistant stores these in ``strings.json``, often as ``[%key:component::domain::path%]``
    references that resolve to a shared string elsewhere.
    """
    strings_path = component_dir / "strings.json"
    try:
        data = json.loads(strings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}, {}

    # A valid JSON file can still parse to a non-object (list, string). Skip it rather
    # than aborting codegen with an AttributeError on the data.get(...) calls below.
    if not isinstance(data, dict):
        return {}, {}

    # ``component::<domain>`` key refs resolve relative to the components/ root (this dir's parent).
    components_dir = component_dir.parent
    service_descs: dict[str, str] = {}
    field_descs: dict[str, dict[str, str]] = {}
    for service_name, service_def in (data.get("services") or {}).items():
        if not isinstance(service_def, dict):
            continue
        raw = service_def.get("description")
        if isinstance(raw, str):
            resolved = _resolve_key_ref(raw, components_dir)
            if resolved:
                service_descs[service_name] = resolved
        field_map: dict[str, str] = {}
        _collect_field_descriptions(service_def.get("fields") or {}, components_dir, field_map)
        field_descs[service_name] = field_map
    return service_descs, field_descs


def _collect_field_descriptions(fields: dict, components_dir: Path, out: dict[str, str]) -> None:
    """Walk a strings.json fields block (including nested sections), resolving each description.

    Accumulates into ``out`` rather than returning so nested section blocks flatten into one map.
    """
    for field_name, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        raw = field_def.get("description")
        if isinstance(raw, str):
            resolved = _resolve_key_ref(raw, components_dir)
            if resolved:
                out[field_name] = resolved
        nested = field_def.get("fields")
        if isinstance(nested, dict):
            _collect_field_descriptions(nested, components_dir, out)


def _resolve_key_ref(value: str, components_dir: Path, depth: int = 0) -> str | None:
    """Resolve a Home Assistant ``[%key:...%]`` translation reference to its literal string.

    A plain (non-reference) string is returned unchanged. A reference is followed to the target
    ``strings.json`` and resolved recursively. ``None`` means the reference could not be resolved —
    a missing file, a broken path, or nesting deeper than ``_MAX_KEY_REF_DEPTH``.
    """
    if depth > _MAX_KEY_REF_DEPTH:
        return None
    match = _KEY_REF.match(value.strip())
    if not match:
        return value
    parts = match.group(1).split("::")
    # Forms: ``component::<domain>::<path>`` (cross-domain) or ``<path>`` (homeassistant base strings).
    if parts and parts[0] == "component":
        if len(parts) < 2:
            return None
        domain, path = parts[1], parts[2:]
    else:
        domain, path = "homeassistant", parts
    try:
        data = json.loads((components_dir / domain / "strings.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for key in path:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return None
    if isinstance(data, str):
        return _resolve_key_ref(data, components_dir, depth + 1)
    return None


@dataclass
class _ServiceRegistration:
    method_name: str | None = None
    supports_response: SupportsResponseValue = "NONE"


def _extract_service_registrations(init_py: Path) -> dict[str, _ServiceRegistration]:
    """Extract service registration calls from __init__.py via AST.

    Returns a dict mapping service_name -> _ServiceRegistration. Service names may be
    raw string literals ("browse_media") or unresolved AST identifiers ("SERVICE_BROWSE_MEDIA",
    "TodoServices.GET_ITEMS") — callers must try multiple lookup forms.
    """
    if not init_py.exists():
        return {}

    try:
        source = init_py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(init_py))
    except SyntaxError:
        return {}

    result: dict[str, _ServiceRegistration] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name = None
        if isinstance(func, ast.Attribute):
            func_name = func.attr
        elif isinstance(func, ast.Name):
            func_name = func.id

        if func_name != "async_register_entity_service":
            continue

        if len(node.args) < 3:
            continue

        service_name_node = node.args[0]
        if isinstance(service_name_node, ast.Constant) and isinstance(service_name_node.value, str):
            service_name = service_name_node.value
        elif isinstance(service_name_node, ast.Name):
            service_name = service_name_node.id
        elif isinstance(service_name_node, ast.Attribute):
            service_name = service_name_node.attr
        else:
            continue

        reg = _ServiceRegistration()

        method_node = node.args[2] if len(node.args) > 2 else None
        if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str):
            reg.method_name = method_node.value

        sr_value = _extract_supports_response(node)
        if sr_value is not None:
            reg.supports_response = sr_value

        result[service_name] = reg

    return result


def _find_registration(
    service_name: str, registrations: dict[str, _ServiceRegistration]
) -> _ServiceRegistration | None:
    """Look up a service registration by yaml service name.

    AST-extracted keys may be string literals ("browse_media"), unresolved constants
    ("SERVICE_BROWSE_MEDIA"), or enum members ("GET_ITEMS"). Try direct match first,
    then normalize: HA convention is SERVICE_<UPPER> or just <UPPER>.
    """
    if service_name in registrations:
        return registrations[service_name]

    upper = service_name.upper()
    for key, reg in registrations.items():
        normalized = key.upper()
        if normalized == upper or normalized == f"SERVICE_{upper}":
            return reg

    return None


def _extract_supports_response(node: ast.Call) -> SupportsResponseValue | None:
    """Extract the SupportsResponse enum member from an async_register_entity_service call.

    Checks both keyword (`supports_response=SupportsResponse.ONLY`) and positional
    (arg index 4) forms. Returns the member name ("NONE", "OPTIONAL", "ONLY") or
    None if the argument is absent or unrecognizable.
    """
    for kw in node.keywords:
        if kw.arg == "supports_response":
            return _resolve_supports_response_node(kw.value)

    if len(node.args) > 4:
        return _resolve_supports_response_node(node.args[4])

    return None


def _resolve_supports_response_node(value_node: ast.expr) -> SupportsResponseValue | None:
    """Resolve an AST node to a SupportsResponse member name."""
    if isinstance(value_node, ast.Attribute) and isinstance(value_node.value, ast.Name):
        if value_node.value.id == "SupportsResponse" and value_node.attr in _VALID_SUPPORTS_RESPONSE:
            return value_node.attr  # pyright: ignore[reportReturnType]
    return None

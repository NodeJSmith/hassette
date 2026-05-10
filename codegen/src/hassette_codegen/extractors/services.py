"""Extract service definitions from services.yaml + AST hybrid."""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ServiceField:
    name: str
    selector_type: str
    selector_data: dict
    required: bool = False


@dataclass
class ExtractedService:
    name: str
    method_name: str
    fields: list[ServiceField] = field(default_factory=list)
    required_features: list[str] = field(default_factory=list)


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

    method_map = _extract_service_registrations(component_dir / "__init__.py")

    services: list[ExtractedService] = []
    for service_name, service_def in raw.items():
        if not isinstance(service_def, dict):
            continue

        fields = _extract_fields(service_def)
        method_name = method_map.get(service_name, service_name)
        required_features = method_map.get(f"{service_name}__features", [])

        services.append(
            ExtractedService(
                name=service_name,
                method_name=method_name if isinstance(method_name, str) else service_name,
                fields=fields,
                required_features=required_features if isinstance(required_features, list) else [],
            )
        )

    return services


def _extract_fields(service_def: dict) -> list[ServiceField]:
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
                        fields.append(_parse_field(sub_name, sub_def))
        else:
            fields.append(_parse_field(field_name, field_def))

    return fields


def _parse_field(name: str, field_def: dict) -> ServiceField:
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
    )


def _extract_service_registrations(init_py: Path) -> dict:
    """Extract service registration calls from __init__.py via AST.

    Returns a dict mapping service_name -> method_name.
    """
    if not init_py.exists():
        return {}

    try:
        source = init_py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(init_py))
    except SyntaxError:
        return {}

    result: dict = {}
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
        else:
            continue

        method_node = node.args[2] if len(node.args) > 2 else None
        if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str):
            result[service_name] = method_node.value

    return result

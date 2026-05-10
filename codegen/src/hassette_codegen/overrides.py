"""Declarative TOML override system for per-domain customization."""

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hassette_codegen.extractors.properties import ExtractedProperty


@dataclass
class PropertyOverride:
    name: str
    wire_name: str | None = None
    type: str | None = None
    add: bool = False


@dataclass
class DomainOverride:
    domain: str
    discovery: str | None = None
    properties: list[ExtractedProperty] = field(default_factory=list)
    property_overrides: list[PropertyOverride] = field(default_factory=list)
    service_param_renames: dict[str, str] = field(default_factory=dict)
    extra_imports: dict[str, list[str]] = field(default_factory=dict)
    param_type_overrides: dict[str, str] = field(default_factory=dict)
    state_base_class: str | None = None


_OVERRIDES_DIR = Path(__file__).resolve().parent / "overrides"


def load_overrides(overrides_dir: Path | None = None) -> dict[str, DomainOverride]:
    """Load all .toml override files from the overrides directory."""
    search_dir = overrides_dir or _OVERRIDES_DIR
    if not search_dir.is_dir():
        return {}

    result: dict[str, DomainOverride] = {}
    for toml_file in sorted(search_dir.glob("*.toml")):
        domain = toml_file.stem
        try:
            data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            print(f"WARNING: Failed to parse override {toml_file}: {exc}", file=sys.stderr)
            continue

        properties = [
            ExtractedProperty(name=p["name"], python_type=p["type"], has_default=True)
            for p in data.get("properties", [])
        ]

        property_overrides = [
            PropertyOverride(
                name=p["name"],
                wire_name=p.get("wire_name"),
                type=p.get("type"),
                add=p.get("add", False),
            )
            for p in data.get("property_overrides", [])
        ]

        result[domain] = DomainOverride(
            domain=domain,
            discovery=data.get("discovery"),
            properties=properties,
            property_overrides=property_overrides,
            service_param_renames=data.get("service_param_renames", {}),
            extra_imports=data.get("extra_imports", {}),
            param_type_overrides=data.get("param_type_overrides", {}),
            state_base_class=data.get("state_base_class"),
        )

    return result


def get_override(overrides: dict[str, DomainOverride], domain: str) -> DomainOverride | None:
    return overrides.get(domain)


def apply_property_overrides(
    properties: list[ExtractedProperty],
    overrides: list[PropertyOverride],
) -> list[ExtractedProperty]:
    """Apply property overrides: rename, retype, or add properties. Returns a new list."""
    if not overrides:
        return properties

    result = [ExtractedProperty(name=p.name, python_type=p.python_type, has_default=p.has_default) for p in properties]

    for ov in overrides:
        if ov.add:
            result.append(
                ExtractedProperty(name=ov.wire_name or ov.name, python_type=ov.type or "str | None", has_default=True)
            )
            continue

        for prop in result:
            if prop.name == ov.name:
                if ov.wire_name:
                    prop.name = ov.wire_name
                if ov.type:
                    prop.python_type = ov.type
                break

    return result


def validate_overrides(
    overrides: dict[str, DomainOverride],
    discovered_domains: set[str],
) -> None:
    """Warn about overrides referencing unknown domains (skips manual discovery domains)."""
    for domain, override in overrides.items():
        if override.discovery == "manual":
            continue
        if domain not in discovered_domains:
            print(f"WARNING: Override file for '{domain}' does not match any discovered domain", file=sys.stderr)

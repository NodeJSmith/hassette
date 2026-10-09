"""Declarative TOML override system for per-domain customization."""

import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from hassette_codegen.extractors.properties import ExtractedProperty

_OVERRIDES_DIR = Path(__file__).resolve().parent / "overrides"


@dataclass
class PropertyOverride:
    name: str
    wire_name: str | None = None
    type: str | None = None
    add: bool = False
    remove: bool = False
    union_mode: str | None = None
    aliases: list[str] = field(default_factory=list)
    """Extra input keys accepted for the field (HA's wire keys). Unlike ``wire_name``, the field name is unchanged."""


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
            ExtractedProperty(name=p["name"], python_type=p["type"], has_default=True, union_mode=p.get("union_mode"))
            for p in data.get("properties", [])
        ]

        property_overrides = [
            PropertyOverride(
                name=p["name"],
                wire_name=p.get("wire_name"),
                type=p.get("type"),
                add=p.get("add", False),
                remove=p.get("remove", False),
                union_mode=p.get("union_mode"),
                aliases=p.get("aliases", []),
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

    result = [replace(p) for p in properties]

    for ov in overrides:
        if ov.add:
            name = ov.wire_name or ov.name
            result.append(
                ExtractedProperty(
                    name=name,
                    python_type=ov.type or "str | None",
                    has_default=True,
                    union_mode=ov.union_mode,
                    validation_aliases=_alias_choices(ov.aliases, name),
                )
            )
            continue

        if ov.remove:
            before = len(result)
            result = [prop for prop in result if prop.name != ov.name]
            if len(result) == before:
                print(f"WARNING: remove override for '{ov.name}' did not match any property", file=sys.stderr)
            continue

        for prop in result:
            if prop.name == ov.name:
                if ov.wire_name:
                    prop.name = ov.wire_name
                if ov.type:
                    prop.python_type = ov.type
                if ov.union_mode:
                    prop.union_mode = ov.union_mode
                if ov.aliases:
                    prop.validation_aliases = _alias_choices(ov.aliases, prop.name)
                break

    return result


def _alias_choices(aliases: list[str], field_name: str) -> tuple[str, ...]:
    """Wire keys first, then the field name, so data keyed by hassette's own field names still validates."""
    if not aliases:
        return ()
    return (*aliases, field_name)


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

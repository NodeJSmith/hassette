"""Declarative TOML override system for per-domain customization."""

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DomainOverride:
    domain: str
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

        result[domain] = DomainOverride(
            domain=domain,
            service_param_renames=data.get("service_param_renames", {}),
            extra_imports=data.get("extra_imports", {}),
            param_type_overrides=data.get("param_type_overrides", {}),
            state_base_class=data.get("state_base_class"),
        )

    return result


def get_override(overrides: dict[str, DomainOverride], domain: str) -> DomainOverride | None:
    return overrides.get(domain)


def validate_overrides(
    overrides: dict[str, DomainOverride],
    discovered_domains: set[str],
) -> None:
    """Warn about overrides referencing unknown domains."""
    for domain in overrides:
        if domain not in discovered_domains:
            print(f"WARNING: Override file for '{domain}' does not match any discovered domain", file=sys.stderr)

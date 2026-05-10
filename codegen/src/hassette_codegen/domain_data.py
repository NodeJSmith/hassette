"""Aggregated extraction results for a single domain."""

from dataclasses import dataclass, field

from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.extractors.services import ExtractedService
from hassette_codegen.overrides import DomainOverride

_TITLE_OVERRIDES: dict[str, str] = {
    "datetime": "DateTime",
}


def domain_to_title(domain_name: str) -> str:
    """Convert a domain name to PascalCase class prefix."""
    if domain_name in _TITLE_OVERRIDES:
        return _TITLE_OVERRIDES[domain_name]
    return domain_name.replace("_", " ").title().replace(" ", "")


@dataclass
class ExtractedDomain:
    name: str
    base_class: str
    properties: list[ExtractedProperty] = field(default_factory=list)
    features: list[ExtractedEnum] = field(default_factory=list)
    strenums: list[ExtractedEnum] = field(default_factory=list)
    services: list[ExtractedService] = field(default_factory=list)
    override: DomainOverride | None = None

"""Aggregated extraction results for a single domain."""

from dataclasses import dataclass, field

from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.extractors.services import ExtractedService
from hassette_codegen.overrides import DomainOverride


@dataclass
class ExtractedDomain:
    name: str
    base_class: str
    properties: list[ExtractedProperty] = field(default_factory=list)
    features: list[ExtractedEnum] = field(default_factory=list)
    services: list[ExtractedService] = field(default_factory=list)
    override: DomainOverride | None = None

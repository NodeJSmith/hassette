"""Report HA core entity domains that hassette has no state model for.

``discover_domains`` only finds components whose entity base class uses ``CACHED_PROPERTIES_WITH_ATTR_``; any
other entity-owning component silently falls back to ``BaseState``. This check scans HA core independently and
reports every entity domain with no generated model, no manual override, and no hand-written model, so a new
upstream domain can't be missed.

A candidate is a component whose ``manifest.json`` declares ``integration_type`` ``entity`` or ``helper`` and whose
top-level modules mention ``EntityComponent`` (helpers that only create entities in existing platform domains, such
as ``template`` or ``utility_meter``, are dropped).

Blind spot: integrations that own an entity domain without declaring ``entity`` or ``helper`` are not checked
(known: homematic, hdmi_cec, configurator, remember_the_milk; all negligible by HA analytics). Domains that are
deliberately unmodeled go in ``coverage_allowlist.toml``; an allowlist entry is stale once its domain is modeled or
its component is removed from HA core.
"""

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hassette_codegen.ha_source import discover_domains
from hassette_codegen.overrides import DomainOverride, load_overrides
from hassette_codegen.pipeline import SIMPLE_STATE_DOMAINS

ALLOWLIST_PATH = Path(__file__).resolve().parent / "coverage_allowlist.toml"
HAND_WRITTEN_STATES_DIR = Path(__file__).resolve().parents[3] / "src" / "hassette" / "models" / "states"
CANDIDATE_INTEGRATION_TYPES = frozenset({"entity", "helper"})
DOMAIN_LITERAL_RE = re.compile(r'domain:\s*Literal\["([a-z0-9_]+)"\]')


@dataclass(frozen=True)
class StaleEntry:
    domain: str
    reason: str


@dataclass(frozen=True)
class CoverageReport:
    gaps: list[str]
    """Candidate domains with no model and no allowlist entry."""
    stale: list[StaleEntry]
    """Allowlist entries whose domain is now modeled or no longer exists in HA core."""

    @property
    def ok(self) -> bool:
        return not self.gaps and not self.stale


def find_coverage_gaps(
    ha_core_path: Path,
    *,
    allowlist: dict[str, str] | None = None,
    overrides: dict[str, DomainOverride] | None = None,
    states_dir: Path = HAND_WRITTEN_STATES_DIR,
) -> CoverageReport:
    """Compare HA core's entity domains against everything hassette models.

    Args:
        ha_core_path: Root of an HA core checkout.
        allowlist: Domain to reason; defaults to ``coverage_allowlist.toml``.
        overrides: Domain overrides; defaults to ``load_overrides()``.
        states_dir: Directory of hand-written state models scanned for ``domain: Literal[...]``.
    """
    components_dir = ha_core_path / "homeassistant" / "components"
    allowlist = load_allowlist() if allowlist is None else allowlist
    overrides = load_overrides() if overrides is None else overrides

    modeled = (
        {d.name for d in discover_domains(ha_core_path)}
        | {name for name, o in overrides.items() if o.discovery == "manual"}
        | SIMPLE_STATE_DOMAINS
        | find_hand_written_domains(states_dir)
    )

    gaps = sorted(d for d in find_candidate_domains(components_dir) if d not in modeled and d not in allowlist)

    stale: list[StaleEntry] = []
    for domain in sorted(allowlist):
        if domain in modeled:
            stale.append(StaleEntry(domain, "now modeled"))
        elif not (components_dir / domain).is_dir():
            stale.append(StaleEntry(domain, "component no longer exists in HA core"))

    return CoverageReport(gaps=gaps, stale=stale)


def find_candidate_domains(components_dir: Path) -> set[str]:
    """Return components declaring an entity/helper integration type that create an ``EntityComponent``."""
    candidates: set[str] = set()
    for component_dir in components_dir.iterdir():
        manifest = component_dir / "manifest.json"
        if not manifest.is_file():
            continue
        integration_type = json.loads(manifest.read_text(encoding="utf-8")).get("integration_type")
        if integration_type not in CANDIDATE_INTEGRATION_TYPES:
            continue
        if any("EntityComponent" in py.read_text(encoding="utf-8") for py in component_dir.glob("*.py")):
            candidates.add(component_dir.name)
    return candidates


def find_hand_written_domains(states_dir: Path) -> set[str]:
    """Return every domain named by a ``domain: Literal["<name>"]`` annotation in the state model modules."""
    domains: set[str] = set()
    for module in states_dir.glob("*.py"):
        domains.update(DOMAIN_LITERAL_RE.findall(module.read_text(encoding="utf-8")))
    return domains


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, str]:
    """Load the allowlist as a domain-to-reason mapping. Every entry must carry a non-empty ``reason``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    allowlist: dict[str, str] = {}
    for domain, entry in data.items():
        reason = entry.get("reason") if isinstance(entry, dict) else None
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path}: allowlist entry [{domain}] needs a non-empty reason")
        allowlist[domain] = reason
    return allowlist


def report_coverage(report: CoverageReport) -> int:
    """Print the report to stdout and return the exit code: 1 when anything needs attention, else 0."""
    for domain in report.gaps:
        print(f"unmodeled domain: {domain}")
    for entry in report.stale:
        print(f"stale allowlist entry: {entry.domain} ({entry.reason})")
    if report.ok:
        print("coverage OK")
        return 0
    return 1

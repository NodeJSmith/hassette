"""Main generation pipeline — wires extractors, generators, and output together."""

import sys
from pathlib import Path
from typing import NamedTuple

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.base_class import determine_base_class
from hassette_codegen.extractors.constants import extract_numeric_state_expected_source, extract_sensor_constants
from hassette_codegen.extractors.features import extract_features, extract_strenum
from hassette_codegen.extractors.properties import extract_properties
from hassette_codegen.extractors.services import extract_services
from hassette_codegen.generators.constants import generate_sensor_constants
from hassette_codegen.generators.entities import generate_entity_wrapper
from hassette_codegen.generators.exports import generate_init_py
from hassette_codegen.generators.states import generate_state_model
from hassette_codegen.ha_source import (
    DiscoveredDomain,
    HASource,
    check_python_version,
    check_ruff_available,
    discover_domains,
)
from hassette_codegen.manifest import (
    detect_orphans,
    is_owned,
    load_manifest,
    manifest_exists,
    merge_manifest,
    save_manifest,
)
from hassette_codegen.output import atomic_write, check_drift
from hassette_codegen.overrides import (
    DomainOverride,
    apply_property_overrides,
    get_override,
    load_overrides,
    validate_overrides,
)
from hassette_codegen.rendering import UnsafeGeneratedValueError, require_identifier

# Hand-written files in the generated packages. A Home Assistant component directory with one of
# these names would otherwise be written straight over them. This list is not redundant with the
# ownership gate in _may_overwrite: on a checkout that has never run the generator there is no
# manifest to consult, and this is what protects these files in that window.
#
# Only basenames that are not themselves Home Assistant domains belong here. The hand-written
# modules that do share a domain name (calendar, zone, person, and the rest) are covered by the
# ownership gate instead — reserving those would permanently block ever generating that domain.
RESERVED_BASENAMES = frozenset({"base", "catalog", "input", "simple", "__init__"})


class Rejection(NamedTuple):
    """Output the pipeline refused to produce because a name from upstream was not safe to use.

    ``domain`` stays a bare domain name so it can be matched against ``--domain``; ``what`` names
    the output that was refused, for the operator reading why the run failed.
    """

    domain: str
    what: str


def run_pipeline(
    ha_source: HASource,
    repo_root: Path,
    *,
    check_mode: bool = False,
    domain_filter: set[str] | None = None,
) -> int:
    """Run the full generation pipeline. Returns exit code (0=ok, 1=drift/skip/rejection)."""
    check_python_version(ha_source.path)
    check_ruff_available()

    all_domains, rejections = _reject_unsafe_domain_names(discover_domains(ha_source.path))
    overrides = load_overrides()

    manual_domains, manual_rejections = _reject_unsafe_domain_names(
        _discover_manual_domains(ha_source.path, overrides, {d.name for d in all_domains})
    )
    all_domains.extend(manual_domains)
    rejections.extend(manual_rejections)
    print(f"Discovered {len(all_domains)} entity domains ({len(manual_domains)} manual)", file=sys.stderr)

    if domain_filter:
        domains = [d for d in all_domains if d.name in domain_filter]
        # A rejection outside the requested filter is not this run's concern, and letting it fail
        # --check would make every filtered run answer for the whole of upstream.
        rejections = [r for r in rejections if r.domain in domain_filter]
        if not domains:
            print(f"WARNING: No domains matched filter: {domain_filter}", file=sys.stderr)
            return 1
    else:
        domains = all_domains

    validate_overrides(overrides, {d.name for d in all_domains})

    previous_manifest = load_manifest(repo_root)
    manifest_tracked = manifest_exists(repo_root)
    generated_files: set[Path] = set()
    # Two ways a domain can come up short, kept apart because they mean different things to the
    # operator: a skip is "the generator tried and could not finish this domain", a rejection is
    # "a name from upstream was not safe to put in generated source, so nothing was attempted".
    # Both fail --check; only skips reduce the generated count in the summary.
    skipped_domains: list[str] = []
    any_drift = False

    states_dir = repo_root / "src" / "hassette" / "models" / "states"
    entities_dir = repo_root / "src" / "hassette" / "models" / "entities"
    const_dir = repo_root / "src" / "hassette" / "const"

    for domain_info in domains:
        try:
            extracted = _extract_domain(ha_source.path, domain_info, overrides)
        except Exception as exc:
            print(f"WARNING: Failed to extract {domain_info.name}: {exc}", file=sys.stderr)
            skipped_domains.append(domain_info.name)
            continue

        state_content = generate_state_model(extracted)
        state_path = states_dir / f"{domain_info.name}.py"
        rel_state = state_path.relative_to(repo_root)

        if check_mode:
            if not check_drift(state_path, state_content, f"{domain_info.name} state model"):
                any_drift = True
            generated_files.add(rel_state)
        else:
            if not _may_overwrite(state_path, rel_state, previous_manifest, tracked=manifest_tracked):
                skipped_domains.append(domain_info.name)
                continue
            if atomic_write(state_path, state_content):
                generated_files.add(rel_state)
            else:
                print(f"WARNING: Skipped {rel_state} (validation failed)", file=sys.stderr)
                skipped_domains.append(domain_info.name)
                continue

        try:
            entity_content = generate_entity_wrapper(extracted)
        except UnsafeGeneratedValueError as exc:
            # The state model above is unaffected and stays generated — only the service wrappers
            # depend on the rejected name, so the domain is not added to skipped_domains. It is
            # still recorded as a rejection: the committed wrapper was never checked against
            # upstream, and --check must not report the tree as current on that basis.
            print(f"WARNING: Rejected {domain_info.name} entity wrapper: {exc}", file=sys.stderr)
            rejections.append(Rejection(domain_info.name, "entity wrapper"))
            continue

        if entity_content is not None:
            entity_path = entities_dir / f"{domain_info.name}.py"
            rel_entity = entity_path.relative_to(repo_root)

            if check_mode:
                if not check_drift(entity_path, entity_content, f"{domain_info.name} entity wrapper"):
                    any_drift = True
                generated_files.add(rel_entity)
            else:
                # Unlike the state model above, the domain is not added to skipped_domains: its
                # state model did generate. The refusal is reported by the warning, matching how
                # an entity wrapper that fails ruff validation is already handled.
                if not _may_overwrite(entity_path, rel_entity, previous_manifest, tracked=manifest_tracked):
                    continue
                if atomic_write(entity_path, entity_content):
                    generated_files.add(rel_entity)
                else:
                    print(f"WARNING: Skipped {rel_entity} (validation failed)", file=sys.stderr)

    constants = extract_sensor_constants(ha_source.path)
    if constants:
        const_content = generate_sensor_constants(constants)
        const_path = const_dir / "sensor.py"
        rel_const = const_path.relative_to(repo_root)

        if check_mode:
            if not check_drift(const_path, const_content, "sensor constants"):
                any_drift = True
            generated_files.add(rel_const)
        elif atomic_write(const_path, const_content):
            # Ownership is only claimed for output this run actually produced. atomic_write
            # reports its own failure, and leaving the path out of the manifest surfaces the
            # retained older copy as an orphan on the next full run.
            generated_files.add(rel_const)

    sensor_init_py = ha_source.path / "homeassistant" / "components" / "sensor" / "__init__.py"
    if check_mode and sensor_init_py.exists():
        # Not a generated-file comparison — this guards the *hand-written* port in
        # sensor_shapes.py against HA changing the logic it was ported from. The fixture test
        # that pins hassette's own behavior can't see that; this can. Scoped to --check (what CI
        # runs) so a plain `generate` run is never blocked by unrelated upstream drift, and
        # scoped to sources that actually have a sensor component so synthetic single-domain
        # test fixtures elsewhere in this suite are unaffected.
        numeric_predicate_snapshot = repo_root / "codegen" / "snapshots" / "numeric_state_expected.py.txt"
        if not _check_predicate_freshness(ha_source.path, numeric_predicate_snapshot):
            any_drift = True

    for pkg_dir in (states_dir, entities_dir):
        init_content = generate_init_py(pkg_dir)
        init_path = pkg_dir / "__init__.py"
        rel_init = init_path.relative_to(repo_root)

        if check_mode:
            if not check_drift(init_path, init_content, f"{pkg_dir.name} __init__.py"):
                any_drift = True
            generated_files.add(rel_init)
        elif atomic_write(init_path, init_content):
            generated_files.add(rel_init)

    if not check_mode:
        if domain_filter:
            merged = merge_manifest(repo_root, domain_filter, generated_files)
            save_manifest(repo_root, merged)
        else:
            orphans = detect_orphans(previous_manifest, generated_files)
            if orphans:
                print(
                    f"Orphaned files (no longer generated): {', '.join(str(p) for p in sorted(orphans))}",
                    file=sys.stderr,
                )
            save_manifest(repo_root, generated_files)

    generated_count = len(domains) - len(skipped_domains)
    print(
        f"Summary: {generated_count} domains generated, {len(skipped_domains)} skipped"
        # Rejections are their own count: a rejected domain never entered `domains`, and a
        # rejected entity wrapper left its domain's state model generated, so neither is
        # visible in the two numbers above.
        + (f", {len(rejections)} rejected" if rejections else "")
        + (
            f", {len(detect_orphans(previous_manifest, generated_files))} orphans"
            if not check_mode and not domain_filter
            else ""
        ),
        file=sys.stderr,
    )

    if check_mode and (any_drift or skipped_domains or rejections):
        if skipped_domains:
            print(f"Skipped domains: {', '.join(skipped_domains)}", file=sys.stderr)
        if rejections:
            print(f"Rejected: {', '.join(f'{r.domain} ({r.what})' for r in rejections)}", file=sys.stderr)
        return 1

    return 0


def _reject_unsafe_domain_names(domains: list[DiscoveredDomain]) -> tuple[list[DiscoveredDomain], list[Rejection]]:
    """Split domains into those safe to generate and the rejections for those dropped.

    A domain name is a Home Assistant component directory name taken verbatim, and it becomes
    both an output filename (``models/states/{name}.py``) and an import path
    (``from hassette.models.states.{name} import ...``). A name that is not an identifier breaks
    the import; a name matching a hand-written module overwrites it silently.

    The rejections are returned rather than only warned about because ``--check`` has to fail on
    them. A dropped domain leaves whatever is committed for it unexamined, which is the same
    "this tree was not verified against upstream" outcome as an extraction failure.
    """
    safe: list[DiscoveredDomain] = []
    rejected: list[Rejection] = []
    for domain in domains:
        if domain.name in RESERVED_BASENAMES:
            print(f"WARNING: Rejected domain '{domain.name}': reserved for hand-written files", file=sys.stderr)
            rejected.append(Rejection(domain.name, "domain name"))
            continue
        try:
            require_identifier(domain.name, kind="domain name")
        except UnsafeGeneratedValueError as exc:
            print(f"WARNING: Rejected domain '{domain.name}': {exc}", file=sys.stderr)
            rejected.append(Rejection(domain.name, "domain name"))
            continue
        safe.append(domain)
    return safe, rejected


def _may_overwrite(out_path: Path, rel_path: Path, previous_manifest: set[Path], *, tracked: bool) -> bool:
    """Whether an existing file may be replaced by generated content.

    First-time generation is always allowed — the target does not exist yet. On a checkout that
    has never run the generator (``tracked`` false) there is no ownership information to consult,
    so the gate falls through rather than refusing every file; this is the case
    ``RESERVED_BASENAMES`` exists to cover, since it is the one moment the ownership check cannot
    protect the hand-written modules. A manifest that exists but lists nothing is a different
    thing — the generator owns nothing, so it may overwrite nothing.

    The manifest passed here must be the *previous* one, which still lists domains a ``--domain``
    run did not process — reading a partially rebuilt manifest would refuse to regenerate files
    the current run legitimately owns.
    """
    if not out_path.exists() or not tracked or is_owned(rel_path, previous_manifest):
        return True

    print(f"WARNING: Refusing to overwrite {rel_path}: exists and is not generator-owned", file=sys.stderr)
    return False


def _check_predicate_freshness(ha_core_path: Path, snapshot_path: Path) -> bool:
    """Verify HA's ``_numeric_state_expected`` predicate source matches the committed snapshot.

    The fixture test that pins hassette's ported behavior (``sensor_shapes.py``) proves hassette's
    logic is stable; it cannot detect Home Assistant changing *their* logic underneath it. This is
    the guard that can. A mismatch — including the extractor failing to find the function at all,
    which means upstream renamed or restructured it — means the ported predicate needs
    re-verification against the new upstream logic before a human updates the snapshot to match.
    """
    current_source = extract_numeric_state_expected_source(ha_core_path)
    if current_source is None:
        print(
            "WARNING: Could not extract Home Assistant's `_numeric_state_expected` predicate for "
            "the freshness check (function not found or source unreadable). The ported predicate "
            "in src/hassette/models/states/sensor_shapes.py must be re-verified against upstream "
            "before the snapshot is updated.",
            file=sys.stderr,
        )
        return False

    if not snapshot_path.exists():
        print(
            f"WARNING: {snapshot_path} does not exist. Cannot verify `_numeric_state_expected` "
            "freshness; create it from the current upstream source.",
            file=sys.stderr,
        )
        return False

    committed_source = snapshot_path.read_text(encoding="utf-8")
    if committed_source.strip() == current_source.strip():
        return True

    print(
        f"WARNING: {snapshot_path} is out of date: Home Assistant's `_numeric_state_expected` "
        "predicate has changed upstream. The ported predicate in "
        "src/hassette/models/states/sensor_shapes.py must be re-verified against the new upstream "
        "logic before updating the snapshot to match.",
        file=sys.stderr,
    )
    return False


def _extract_domain(
    ha_core_path: Path, domain_info: DiscoveredDomain, overrides: dict[str, DomainOverride]
) -> ExtractedDomain:
    """Extract all data for a single domain."""
    override = get_override(overrides, domain_info.name)

    if override and override.discovery == "manual":
        return _extract_manual_domain(domain_info, override)

    init_py = domain_info.path / "__init__.py"

    features = extract_features(domain_info.path)
    strenums = extract_strenum(domain_info.path)
    properties = extract_properties(init_py)
    base_class = determine_base_class(init_py)
    services = extract_services(domain_info.path) if domain_info.has_services_yaml else []

    if override and override.property_overrides:
        properties = apply_property_overrides(properties, override.property_overrides)

    return ExtractedDomain(
        name=domain_info.name,
        base_class=base_class,
        properties=properties,
        features=features,
        strenums=strenums,
        services=services,
        override=override,
    )


def _extract_manual_domain(domain_info: DiscoveredDomain, override: DomainOverride) -> ExtractedDomain:
    """Build an ExtractedDomain from TOML-declared properties."""
    base_class = override.state_base_class or "StringBaseState"
    services = extract_services(domain_info.path) if domain_info.has_services_yaml else []

    return ExtractedDomain(
        name=domain_info.name,
        base_class=base_class,
        properties=list(override.properties),
        features=[],
        strenums=[],
        services=services,
        override=override,
    )


def _discover_manual_domains(
    ha_core_path: Path,
    overrides: dict[str, DomainOverride],
    already_discovered: set[str],
) -> list[DiscoveredDomain]:
    """Create DiscoveredDomain entries for manual override domains not already discovered."""
    components_dir = ha_core_path / "homeassistant" / "components"
    manual: list[DiscoveredDomain] = []

    for domain, override in overrides.items():
        if override.discovery != "manual":
            continue
        if domain in already_discovered:
            continue

        domain_path = components_dir / domain
        if not domain_path.is_dir():
            print(f"WARNING: Manual domain '{domain}' not found at {domain_path}", file=sys.stderr)
            continue

        manual.append(
            DiscoveredDomain(
                name=domain,
                path=domain_path,
                has_services_yaml=(domain_path / "services.yaml").exists(),
                has_const_py=(domain_path / "const.py").exists(),
            )
        )

    return manual

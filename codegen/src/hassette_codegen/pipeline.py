"""Main generation pipeline — wires extractors, generators, and output together."""

import sys
from pathlib import Path

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.base_class import determine_base_class
from hassette_codegen.extractors.constants import extract_sensor_constants
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
RESERVED_BASENAMES = frozenset({"base", "catalog", "__init__"})


def run_pipeline(
    ha_source: HASource,
    repo_root: Path,
    *,
    check_mode: bool = False,
    domain_filter: set[str] | None = None,
) -> int:
    """Run the full generation pipeline. Returns exit code (0=ok, 1=drift/skip)."""
    check_python_version(ha_source.path)
    check_ruff_available()

    all_domains = _reject_unsafe_domain_names(discover_domains(ha_source.path))
    overrides = load_overrides()

    manual_domains = _reject_unsafe_domain_names(
        _discover_manual_domains(ha_source.path, overrides, {d.name for d in all_domains})
    )
    all_domains.extend(manual_domains)
    print(f"Discovered {len(all_domains)} entity domains ({len(manual_domains)} manual)", file=sys.stderr)

    if domain_filter:
        domains = [d for d in all_domains if d.name in domain_filter]
        if not domains:
            print(f"WARNING: No domains matched filter: {domain_filter}", file=sys.stderr)
            return 1
    else:
        domains = all_domains

    validate_overrides(overrides, {d.name for d in all_domains})

    previous_manifest = load_manifest(repo_root)
    manifest_tracked = manifest_exists(repo_root)
    generated_files: set[Path] = set()
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
            # depend on the rejected name.
            print(f"WARNING: Skipped {domain_info.name} entity wrapper: {exc}", file=sys.stderr)
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
        else:
            atomic_write(const_path, const_content)

        generated_files.add(rel_const)

    for pkg_dir in (states_dir, entities_dir):
        init_content = generate_init_py(pkg_dir)
        init_path = pkg_dir / "__init__.py"
        rel_init = init_path.relative_to(repo_root)

        if check_mode:
            if not check_drift(init_path, init_content, f"{pkg_dir.name} __init__.py"):
                any_drift = True
        else:
            atomic_write(init_path, init_content)

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
        + (
            f", {len(detect_orphans(previous_manifest, generated_files))} orphans"
            if not check_mode and not domain_filter
            else ""
        ),
        file=sys.stderr,
    )

    if check_mode and (any_drift or skipped_domains):
        if skipped_domains:
            print(f"Skipped domains: {', '.join(skipped_domains)}", file=sys.stderr)
        return 1

    return 0


def _reject_unsafe_domain_names(domains: list[DiscoveredDomain]) -> list[DiscoveredDomain]:
    """Drop domains whose name cannot safely become a module.

    A domain name is a Home Assistant component directory name taken verbatim, and it becomes
    both an output filename (``models/states/{name}.py``) and an import path
    (``from hassette.models.states.{name} import ...``). A name that is not an identifier breaks
    the import; a name matching a hand-written module overwrites it silently.
    """
    safe: list[DiscoveredDomain] = []
    for domain in domains:
        if domain.name in RESERVED_BASENAMES:
            print(f"WARNING: Skipping domain '{domain.name}': reserved for hand-written files", file=sys.stderr)
            continue
        try:
            require_identifier(domain.name, kind="domain name")
        except UnsafeGeneratedValueError as exc:
            print(f"WARNING: Skipping domain '{domain.name}': {exc}", file=sys.stderr)
            continue
        safe.append(domain)
    return safe


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

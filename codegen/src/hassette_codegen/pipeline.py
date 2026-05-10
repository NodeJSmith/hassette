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
from hassette_codegen.ha_source import HASource, check_python_version, check_ruff_available, discover_domains
from hassette_codegen.manifest import detect_orphans, load_manifest, merge_manifest, save_manifest
from hassette_codegen.output import atomic_write, check_drift
from hassette_codegen.overrides import get_override, load_overrides, validate_overrides


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

    all_domains = discover_domains(ha_source.path)
    print(f"Discovered {len(all_domains)} entity domains", file=sys.stderr)

    if domain_filter:
        domains = [d for d in all_domains if d.name in domain_filter]
        if not domains:
            print(f"WARNING: No domains matched filter: {domain_filter}", file=sys.stderr)
            return 1
    else:
        domains = all_domains

    overrides = load_overrides()
    validate_overrides(overrides, {d.name for d in all_domains})

    previous_manifest = load_manifest(repo_root)
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
        else:
            if atomic_write(state_path, state_content):
                generated_files.add(rel_state)
            else:
                print(f"WARNING: Skipped {rel_state} (validation failed)", file=sys.stderr)
                skipped_domains.append(domain_info.name)
                continue

        generated_files.add(rel_state)

        entity_content = generate_entity_wrapper(extracted)
        if entity_content is not None:
            entity_path = entities_dir / f"{domain_info.name}.py"
            rel_entity = entity_path.relative_to(repo_root)

            if check_mode:
                if not check_drift(entity_path, entity_content, f"{domain_info.name} entity wrapper"):
                    any_drift = True
            else:
                if atomic_write(entity_path, entity_content):
                    generated_files.add(rel_entity)
                else:
                    print(f"WARNING: Skipped {rel_entity} (validation failed)", file=sys.stderr)

            generated_files.add(rel_entity)

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

    if skipped_domains and check_mode:
        return 1

    return 0


def _extract_domain(ha_core_path: Path, domain_info: object, overrides: dict) -> ExtractedDomain:
    """Extract all data for a single domain."""
    init_py = domain_info.path / "__init__.py"

    features = extract_features(domain_info.path)
    strenums = extract_strenum(domain_info.path)
    properties = extract_properties(init_py)
    base_class = determine_base_class(init_py)
    services = extract_services(domain_info.path) if domain_info.has_services_yaml else []
    override = get_override(overrides, domain_info.name)

    return ExtractedDomain(
        name=domain_info.name,
        base_class=base_class,
        properties=properties,
        features=features,
        strenums=strenums,
        services=services,
        override=override,
    )

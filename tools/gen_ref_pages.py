"""Generate per-module reference stubs for mkdocstrings."""

import os
import shutil
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
VIRTUAL_REF_ROOT = Path("reference")
DEBUG = bool(os.environ.get("GEN_REF_DEBUG"))

# Public API allowlist — derived from nav audit Section 6.
# Only modules in this set will have reference stubs generated.
# Seeded from hassette.__all__ (Tier A) plus curated additions (Tier B).
PUBLIC_MODULES: frozenset[str] = frozenset(
    {
        # --- Tier A: hassette.__all__ entries ---
        "hassette.app",  # App, AppConfig, AppSync, only_app
        "hassette.api",  # Api
        "hassette.bus",  # Bus
        "hassette.scheduler",  # Scheduler
        "hassette.core.core",  # Hassette (entrypoint)
        "hassette.config",  # HassetteConfig
        "hassette.const",  # ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
        "hassette.conversion",  # STATE_REGISTRY, TYPE_REGISTRY, TypeConverterEntry, register_*
        "hassette.events",  # RawStateChangeEvent
        "hassette.models.services",  # ServiceResponse
        "hassette.models.entities",  # entities module
        "hassette.models.states",  # states module
        "hassette.task_bucket",  # TaskBucket
        "hassette.event_handling.accessors",  # A / accessors
        "hassette.event_handling.conditions",  # C / conditions
        "hassette.event_handling.dependencies",  # D / dependencies
        "hassette.event_handling.predicates",  # P / predicates
        # --- Tier B: curated additions beyond __all__ ---
        "hassette.models.states.base",  # BaseState, StringBaseState, NumericBaseState, etc.
        "hassette.scheduler.classes",  # ScheduledJob
        "hassette.test_utils",  # AppTestHarness, RecordingApi, event factories, etc.
        # --- Tier C: autoref targets in narrative docs ---
        "hassette.exceptions",  # HassetteError, EntityNotFoundError, InvalidAuthError, CannotOverrideFinalError
        "hassette.resources.base",  # Resource lifecycle hooks (before/on/after_initialize, before/on/after_shutdown)
        "hassette.state_manager.state_manager",  # StateManager, DomainStates
        "hassette.bus.extraction",  # BusExtraction type used in dependency injection docs
    }
)


def format_title(part: str) -> str:
    return " ".join(word.capitalize() for word in part.split("_"))


def main() -> None:
    nav = mkdocs_gen_files.Nav()

    ref_disk_dir = ROOT / "docs" / VIRTUAL_REF_ROOT
    if ref_disk_dir.exists():
        shutil.rmtree(ref_disk_dir)

    if DEBUG:
        print("[gen-ref] generating API reference stubs...", flush=True)

    for path in sorted(SRC_DIR.rglob("*.py")):
        module_parts = path.relative_to(SRC_DIR).with_suffix("").parts

        if not module_parts:
            continue

        if module_parts[-1] in {"__main__", "__version__"}:
            continue

        doc_path = Path(*module_parts).with_suffix(".md")
        full_doc_path = VIRTUAL_REF_ROOT / doc_path
        parts = module_parts

        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
            doc_path = doc_path.with_name("index.md")
            full_doc_path = full_doc_path.with_name("index.md")

        module_path = ".".join(parts)

        if module_path not in PUBLIC_MODULES:
            if DEBUG:
                print(f"[gen-ref] skipping {module_path} (not in allowlist)")
            continue

        nav_entry = [format_title(part) for part in parts]
        nav[nav_entry] = doc_path.as_posix()

        if DEBUG:
            print(f"[gen-ref] writing {full_doc_path} for {module_path}")

        with mkdocs_gen_files.open(full_doc_path, "w") as fd:
            fd.write(f"::: {module_path}\n")

        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(ROOT))

    summary_path = VIRTUAL_REF_ROOT / "SUMMARY.md"
    with mkdocs_gen_files.open(summary_path, "w") as nav_file:
        nav_file.writelines(nav.build_literate_nav())


if __name__ in {"__main__", "<run_path>"}:
    main()

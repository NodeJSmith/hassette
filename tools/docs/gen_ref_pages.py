"""Generate per-module reference stubs for mkdocstrings."""

import os
import shutil
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
VIRTUAL_REF_ROOT = Path("reference")
DEBUG = bool(os.environ.get("GEN_REF_DEBUG"))

# Public API allowlist — derived from nav audit Section 6.
# Only modules in this set will have reference stubs generated.
# Seeded from hassette.__all__ (Tier A) plus curated additions (Tier B).
PUBLIC_MODULES: frozenset[str] = frozenset(
    {
        # Tier A: hassette.__all__ entries
        "hassette.app",  # App, AppConfig, AppSync, only_app
        "hassette.api",  # Api
        "hassette.api.sync",  # ApiSyncFacade
        "hassette.bus",  # Bus
        "hassette.scheduler",  # Scheduler
        "hassette.core.core",  # Hassette (entrypoint)
        "hassette.config",  # HassetteConfig
        "hassette.const",  # ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
        "hassette.conversion",  # STATE_REGISTRY, TYPE_REGISTRY, TypeConverterEntry, register_*
        "hassette.events",  # RawStateChangeEvent
        "hassette.models.history",  # HistoryEntry
        "hassette.models.services",  # ServiceResponse
        "hassette.models.entities",  # entities module
        "hassette.models.states",  # states module
        "hassette.task_bucket",  # TaskBucket
        "hassette.event_handling.accessors",  # A / accessors
        "hassette.event_handling.conditions",  # C / conditions
        "hassette.event_handling.dependencies",  # D / dependencies
        "hassette.event_handling.predicates",  # P / predicates
        # Tier B: curated additions beyond __all__
        "hassette.models.states.base",  # BaseState, StringBaseState, NumericBaseState, etc.
        "hassette.scheduler.classes",  # ScheduledJob
        "hassette.test_utils",  # AppTestHarness, RecordingApi, event factories, etc.
        # Tier C: autoref targets in narrative docs
        "hassette.exceptions",  # HassetteError, EntityNotFoundError, InvalidAuthError, HassetteForgottenAwaitWarning
        # ForgottenAwaitBehavior, ResourceStatus, RestartType, and other framework enums
        "hassette.types.enums",
        "hassette.state_manager.state_manager",  # StateManager, DomainStates
        "hassette.di",  # AnnotationDetails, build_injection_plan, TypeMatcher, AnnotatedMatcher, etc.
        "hassette.resources.base",  # Resource base class referenced in lifecycle/internals docs
        "hassette.resources.service",  # Service base class referenced in internals docs
        "hassette.execution_mode",  # ExecutionModeGuard, DEFAULT_QUEUE_DEPTH referenced in bus docs
        "hassette.bus.listeners",  # Subscription, Listener referenced in bus docs
        "hassette.bus.error_context",  # BusErrorContext referenced in handler docs
        "hassette.events.hass.hass",  # RawStateChangeEvent, CallServiceEvent, ComponentLoadedEvent
        "hassette.config.classes",  # AppManifest referenced in config docs
        "hassette.scheduler.error_context",  # SchedulerErrorContext referenced in scheduler docs
        "hassette.types",  # Public type aliases: HandlerType, Predicate, ChangeType, TriggerProtocol, etc.
        "hassette.types.types",  # Type definitions for handler, predicate, trigger, and change types
        "hassette.resources.restart",  # RestartSpec referenced in lifecycle docs
        "hassette.core.service_watcher",  # ServiceWatcher referenced in internals/operating docs
        "hassette.core.websocket_service",  # WebsocketService referenced in internals/operating docs
        "hassette.core.bus_service",  # BusService referenced in internals docs
        "hassette.core.scheduler_service",  # SchedulerService referenced in internals docs
        "hassette.core.database_service",  # DatabaseService referenced in internals docs
        "hassette.core.state_proxy",  # StateProxy referenced in internals/operating docs
        "hassette.core.web_api_service",  # WebApiService referenced in internals docs
        "hassette.core.event_stream_service",  # EventStreamService referenced in internals docs
        "hassette.core.command_executor",  # CommandExecutor referenced in internals docs
        "hassette.core.api_resource",  # ApiResource referenced in internals docs
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

    # Write the reference overview page first so it appears at the top of the nav.
    index_content = (
        "# API Reference\n\n"
        "The API reference is auto-generated from source docstrings."
        " It covers all public modules in Hassette.\n\n"
        "Browse the modules in the navigation sidebar, or jump directly to a section:\n\n"
        "- **App** — [hassette.app](hassette/app/index.md)"
        " · [hassette.core.core](hassette/core/core.md)"
        " · [hassette.config](hassette/config/index.md)\n"
        "- **Event handling** — [hassette.bus](hassette/bus/index.md)"
        " · [hassette.events](hassette/events/hass/hass.md)"
        " · [hassette.event_handling](hassette/event_handling/predicates.md)\n"
        "- **API & States** — [hassette.api](hassette/api/index.md)"
        " · [hassette.scheduler](hassette/scheduler/index.md)"
        " · [hassette.state_manager](hassette/state_manager/state_manager.md)"
        " · [hassette.models.states](hassette/models/states/index.md)\n"
        "- **Type system** — [hassette.conversion](hassette/conversion/index.md)"
        " · [hassette.const](hassette/const/index.md)"
        " · [hassette.types.enums](hassette/types/enums.md)\n"
        "- **Testing** — [hassette.test_utils](hassette/test_utils/index.md)\n"
        "- **Utilities** — [hassette.task_bucket](hassette/task_bucket/index.md)"
        " · [hassette.exceptions](hassette/exceptions.md)\n"
    )
    with mkdocs_gen_files.open(VIRTUAL_REF_ROOT / "index.md", "w") as index_file:
        index_file.write(index_content)
    nav[["Overview"]] = "index.md"

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

        nav_parts = parts[1:] if parts[0] == "hassette" and len(parts) > 1 else parts
        nav_entry = [format_title(part) for part in nav_parts]
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

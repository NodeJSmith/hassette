---
task_id: "T01"
title: "Move contract enums, Literals, and CliFormat into hassette_wire"
status: "planned"
depends_on: []
implements: ["FR#5", "FR#6", "FR#7", "FR#8", "AC#3", "AC#12", "AC#13"]
---

## Summary
Moves the wire-contract vocabulary — `ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy`, `ExecutionStatus`, `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier`, `CliFormat`, `CliFormatStyle` — out of `hassette.types` into `hassette_wire`, with one definition and no mirrors. The `hassette` root gains `ResourceStatus` and `ExecutionStatus` alongside the existing `ExecutionMode`/`BackpressurePolicy` re-exports, and every other old path stops resolving (breaking change). Every in-repo import is rewritten to `from hassette_wire import …`, including the sync-facade code generator, and docs cross-references move to `hassette.ResourceStatus`. The models still live where they are; T02 moves them.

## Target Files
- create: `wire/src/hassette_wire/enums.py`
- create: `wire/src/hassette_wire/literals.py`
- create: `wire/src/hassette_wire/cli_format.py`
- create: `tests/unit/test_wire_public_paths.py`
- modify: `wire/src/hassette_wire/__init__.py`
- modify: `src/hassette/__init__.py`
- modify: `src/hassette/types/__init__.py`
- modify: `src/hassette/types/enums.py`
- modify: `src/hassette/types/types.py`
- modify: `src/hassette/schemas/__init__.py`
- modify: `codegen/src/hassette_codegen/sync_facade/generic.py`
- modify: `tools/docs/check_xref_coverage.py`
- modify: `mkdocs.yml`
- modify: `docs/pages/core-concepts/internals/lifecycle.md`
- modify: `docs/pages/core-concepts/bus/methods.md`
- modify: `docs/pages/testing/snippets/testing_simulate_service_failure.py`
- modify: `src/hassette/cli/output.py`
- modify: `scripts/seed_scenarios/base.py` (import rewrite)
- modify: `scripts/seed_scenarios/degraded.py` (import rewrite)
- modify: `src/hassette/api/api.py` (import rewrite)
- modify: `src/hassette/api/helpers.py` (import rewrite)
- modify: `src/hassette/api/sync.py` (import rewrite)
- modify: `src/hassette/api/sync_helpers.py` (import rewrite)
- modify: `src/hassette/app/app.py` (import rewrite)
- modify: `src/hassette/app/app_config.py` (import rewrite)
- modify: `src/hassette/bus/bus.py` (import rewrite)
- modify: `src/hassette/bus/listeners.py` (import rewrite)
- modify: `src/hassette/bus/options.py` (import rewrite)
- modify: `src/hassette/bus/sync.py` (import rewrite)
- modify: `src/hassette/bus/sync_events.py` (import rewrite)
- modify: `src/hassette/commands.py` (import rewrite)
- modify: `src/hassette/config/helpers.py` (import rewrite)
- modify: `src/hassette/config/models.py` (import rewrite)
- modify: `src/hassette/core/api_resource.py` (import rewrite)
- modify: `src/hassette/core/app_bootstrap_coordinator.py` (import rewrite)
- modify: `src/hassette/core/app_handler.py` (import rewrite)
- modify: `src/hassette/core/app_lifecycle_service.py` (import rewrite)
- modify: `src/hassette/core/app_registry.py` (import rewrite)
- modify: `src/hassette/core/bus_service.py` (import rewrite)
- modify: `src/hassette/core/command_executor.py` (import rewrite)
- modify: `src/hassette/core/core.py` (import rewrite)
- modify: `src/hassette/core/database_service.py` (import rewrite)
- modify: `src/hassette/core/event_stream_service.py` (import rewrite)
- modify: `src/hassette/core/execution_pipeline.py` (import rewrite)
- modify: `src/hassette/core/execution_record.py` (import rewrite)
- modify: `src/hassette/core/file_watcher.py` (import rewrite)
- modify: `src/hassette/core/registration.py` (import rewrite)
- modify: `src/hassette/core/retention_targets.py` (import rewrite)
- modify: `src/hassette/core/runtime_query_service.py` (import rewrite)
- modify: `src/hassette/core/scheduler_service.py` (import rewrite)
- modify: `src/hassette/core/service_watcher.py` (import rewrite)
- modify: `src/hassette/core/session_manager.py` (import rewrite)
- modify: `src/hassette/core/state_proxy.py` (import rewrite)
- modify: `src/hassette/core/telemetry/execution_queries.py` (import rewrite)
- modify: `src/hassette/core/telemetry/helpers.py` (import rewrite)
- modify: `src/hassette/core/telemetry/query_service.py` (import rewrite)
- modify: `src/hassette/core/telemetry/registration_queries.py` (import rewrite)
- modify: `src/hassette/core/telemetry/repository.py` (import rewrite)
- modify: `src/hassette/core/telemetry/summary_queries.py` (import rewrite)
- modify: `src/hassette/core/web_api_service.py` (import rewrite)
- modify: `src/hassette/core/web_ui_watcher.py` (import rewrite)
- modify: `src/hassette/core/websocket_service.py` (import rewrite)
- modify: `src/hassette/events/hassette.py` (import rewrite)
- modify: `src/hassette/execution_mode.py` (import rewrite)
- modify: `src/hassette/resources/base.py` (import rewrite)
- modify: `src/hassette/resources/lifecycle.py` (import rewrite)
- modify: `src/hassette/resources/mixins.py` (import rewrite)
- modify: `src/hassette/resources/service.py` (import rewrite)
- modify: `src/hassette/scheduler/classes.py` (import rewrite)
- modify: `src/hassette/scheduler/scheduler.py` (import rewrite)
- modify: `src/hassette/scheduler/sync.py` (import rewrite)
- modify: `src/hassette/schemas/app_snapshots.py` (import rewrite)
- modify: `src/hassette/schemas/domain_models.py` (import rewrite)
- modify: `src/hassette/schemas/execution_models.py` (import rewrite)
- modify: `src/hassette/schemas/job_models.py` (import rewrite)
- modify: `src/hassette/schemas/listener_models.py` (import rewrite)
- modify: `src/hassette/schemas/log_models.py` (import rewrite)
- modify: `src/hassette/state_manager/state_manager.py` (import rewrite)
- modify: `src/hassette/task_bucket/task_bucket.py` (import rewrite)
- modify: `src/hassette/testing/_harness.py` (import rewrite)
- modify: `src/hassette/testing/_reset.py` (import rewrite)
- modify: `src/hassette/testing/_simulation.py` (import rewrite)
- modify: `src/hassette/testing/app_harness.py` (import rewrite)
- modify: `src/hassette/utils/execution.py` (import rewrite)
- modify: `src/hassette/web/dependencies.py` (import rewrite)
- modify: `src/hassette/web/mappers.py` (import rewrite)
- modify: `src/hassette/web/models.py` (import rewrite)
- modify: `tests/e2e/mock_fixtures/manifests.py` (import rewrite)
- modify: `tests/integration/conftest.py` (import rewrite)
- modify: `tests/integration/telemetry/helpers.py` (import rewrite)
- modify: `tests/integration/telemetry/test_global_jobs_and_service_info.py` (import rewrite)
- modify: `tests/integration/test_app_factory_lifecycle.py` (import rewrite)
- modify: `tests/integration/test_app_test_harness.py` (import rewrite)
- modify: `tests/integration/test_command_executor.py` (import rewrite)
- modify: `tests/integration/test_hot_reload.py` (import rewrite)
- modify: `tests/integration/test_lifecycle_propagation.py` (import rewrite)
- modify: `tests/integration/test_registration.py` (import rewrite)
- modify: `tests/integration/test_scheduler_mode.py` (import rewrite)
- modify: `tests/integration/test_service_watcher.py` (import rewrite)
- modify: `tests/integration/web_api/test_endpoints.py` (import rewrite)
- modify: `tests/integration/web_api/test_telemetry_route.py` (import rewrite)
- modify: `tests/integration/web_api/test_ws_endpoint.py` (import rewrite)
- modify: `tests/support/factories.py` (import rewrite)
- modify: `tests/support/helpers.py` (import rewrite)
- modify: `tests/support/web_job_helpers.py` (import rewrite)
- modify: `tests/support/web_manifest_helpers.py` (import rewrite)
- modify: `tests/support/web_mocks.py` (import rewrite)
- modify: `tests/support/web_telemetry_helpers.py` (import rewrite)
- modify: `tests/system/test_app_lifecycle.py` (import rewrite)
- modify: `tests/system/test_shutdown.py` (import rewrite)
- modify: `tests/unit/bus/test_bus_registration_edge_cases.py` (import rewrite)
- modify: `tests/unit/bus/test_execution_mode_guard.py` (import rewrite)
- modify: `tests/unit/bus/test_listeners.py` (import rewrite)
- modify: `tests/unit/cli/test_output.py` (import rewrite)
- modify: `tests/unit/cli/test_output_detail.py` (import rewrite)
- modify: `tests/unit/core/_fixtures_app_lifecycle.py` (import rewrite)
- modify: `tests/unit/core/_fixtures_app_registry.py` (import rewrite)
- modify: `tests/unit/core/_fixtures_service_watcher.py` (import rewrite)
- modify: `tests/unit/core/test_app_lifecycle_service_instances.py` (import rewrite)
- modify: `tests/unit/core/test_app_lifecycle_service_per_instance_ops.py` (import rewrite)
- modify: `tests/unit/core/test_app_lifecycle_service_start_stop.py` (import rewrite)
- modify: `tests/unit/core/test_app_registry.py` (import rewrite)
- modify: `tests/unit/core/test_app_registry_snapshot.py` (import rewrite)
- modify: `tests/unit/core/test_bus_dispatch_semaphore.py` (import rewrite)
- modify: `tests/unit/core/test_command_executor.py` (import rewrite)
- modify: `tests/unit/core/test_command_executor_pipeline_filter.py` (import rewrite)
- modify: `tests/unit/core/test_command_executor_pipeline_persist.py` (import rewrite)
- modify: `tests/unit/core/test_core_coverage.py` (import rewrite)
- modify: `tests/unit/core/test_database_service.py` (import rewrite)
- modify: `tests/unit/core/test_execution_timeout.py` (import rewrite)
- modify: `tests/unit/core/test_overlay_runtime_state.py` (import rewrite)
- modify: `tests/unit/core/test_runtime_query_service.py` (import rewrite)
- modify: `tests/unit/core/test_scheduler_mode_resolution.py` (import rewrite)
- modify: `tests/unit/core/test_scheduler_service_trigger.py` (import rewrite)
- modify: `tests/unit/core/test_service_watcher_coverage.py` (import rewrite)
- modify: `tests/unit/core/test_service_watcher_exhausted.py` (import rewrite)
- modify: `tests/unit/core/test_unified_execution.py` (import rewrite)
- modify: `tests/unit/events/test_hassette_payload.py` (import rewrite)
- modify: `tests/unit/events/test_service_status_payload.py` (import rewrite)
- modify: `tests/unit/resources/conftest.py` (import rewrite)
- modify: `tests/unit/resources/lifecycle/test_force_terminal.py` (import rewrite)
- modify: `tests/unit/resources/lifecycle/test_init.py` (import rewrite)
- modify: `tests/unit/resources/lifecycle/test_shutdown.py` (import rewrite)
- modify: `tests/unit/resources/lifecycle/test_total_timeout.py` (import rewrite)
- modify: `tests/unit/resources/test_add_child_and_restart.py` (import rewrite)
- modify: `tests/unit/resources/test_direct_status_assignments.py` (import rewrite)
- modify: `tests/unit/resources/test_emit_readiness_event.py` (import rewrite)
- modify: `tests/unit/resources/test_lifecycle_transitions.py` (import rewrite)
- modify: `tests/unit/resources/test_run_hooks.py` (import rewrite)
- modify: `tests/unit/resources/test_serve_wrapper_shutdown.py` (import rewrite)
- modify: `tests/unit/resources/test_service_edge_cases.py` (import rewrite)
- modify: `tests/unit/resources/test_shutdown_edge_cases.py` (import rewrite)
- modify: `tests/unit/scheduler/test_scheduled_job_lifecycle.py` (import rewrite)
- modify: `tests/unit/test_app_key.py` (import rewrite)
- modify: `tests/unit/test_config_log_level.py` (import rewrite)
- modify: `tests/unit/test_execution.py` (import rewrite)
- modify: `tests/unit/test_execution_mode_helpers.py` (import rewrite)
- modify: `tests/unit/test_harness_coverage.py` (import rewrite)
- modify: `tests/unit/test_model_types.py` (import rewrite)
- modify: `tests/unit/test_schema_migration.py` (import rewrite)
- modify: `tests/unit/test_source_tier_propagation.py` (import rewrite)
- modify: `tests/unit/test_ws_models.py` (import rewrite)
- modify: `tests/unit/web/test_mappers.py` (import rewrite)
- read: `design/specs/116-wire-models-to-hassette-wire/design.md`
- read: `tests/unit/tools/test_generate_sync_facade.py`
- read: `prek.toml`

## Prompt
Read `tasks/context.md` and these design sections first: `### Enums and Literals: one definition, re-exported only at the public root`, `### Import rewrite`, `## Edge Cases` (enum identity, removed import paths, enum descriptions, defaults, docs cross-references), `## Replacement Targets`, `## Key Constraints`.

1. **Create the wire modules by moving code, not retyping it.**
   - `wire/src/hassette_wire/enums.py`: move `ExecutionMode`, `BackpressurePolicy`, `ResourceStatus`, `ManifestStatus` from `src/hassette/types/enums.py` and `ExecutionStatus` from `src/hassette/types/types.py`. Keep class docstrings and per-member docstrings byte-exact. Replace every `auto()` with the explicit string value it produced today (the lowercased member name — confirm each by reading the current `.value`, e.g. `python -c "from hassette.types.enums import ResourceStatus; print([m.value for m in ResourceStatus])"` BEFORE moving).
   - `wire/src/hassette_wire/literals.py`: move `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier` from `types/types.py` (with any comments/docstrings attached). T02 adds the web-model Literals here later.
   - `wire/src/hassette_wire/cli_format.py`: move `CliFormat` and `CliFormatStyle` from `types/types.py`.
   - `wire/src/hassette_wire/__init__.py`: re-export every moved name from the root and list it in `__all__`. Keep the existing package docstring for now (T07 rewrites it).
2. **Remove the old definitions with no re-exports.** Delete the moved definitions from `src/hassette/types/enums.py` and `types/types.py`. Code that stays in those modules and needs a moved enum (`DEFAULT_OVERLAP_MODE`, `DEFAULT_BACKPRESSURE_POLICY`, `TERMINAL_STATUSES`, `ACTIVE_STATUSES`, and anything else that references one) must not bring the name back as a module attribute, because AC#3 asserts `not hasattr(hassette.types.enums, "ResourceStatus")` etc. Use `import hassette_wire` and qualified references (`hassette_wire.ResourceStatus.STOPPED`) there, never `from hassette_wire import ResourceStatus`. Add a short note to both module docstrings: the contract enums/Literals live in `hassette_wire`, and app authors import them from `hassette`. `src/hassette/types/__init__.py` drops `BackpressurePolicy`, `ExecutionMode`, `ResourceStatus`, `QuerySourceTier`, `SourceTier` from its imports and `__all__`. `src/hassette/schemas/__init__.py` drops its `ManifestStatus` import and `__all__` entry.
3. **Public root.** In `src/hassette/__init__.py`, follow the design's "Public re-export surface" convention example: import `BackpressurePolicy, ExecutionMode, ExecutionStatus, ResourceStatus` from `hassette_wire`, keep the remaining `.types.enums` names, and add `ResourceStatus` and `ExecutionStatus` to `__all__`.
4. **Rewrite imports with a one-off script** (do not commit it; keep it in your scratch dir). For every file in Target Files marked "import rewrite", replace imports of the moved names from `hassette.types`, `hassette.types.enums`, `hassette.types.types`, or `hassette.schemas` (ManifestStatus only) with `from hassette_wire import …`. Names that stay (e.g. `Topic`, `IfExistsPolicy`, `WhereClause`) keep their original import line. Use `ast` to locate `ImportFrom` nodes so multi-line parenthesized imports are handled; preserve `TYPE_CHECKING` placement. Then run `prek -a` (ruff/isort) to normalize ordering.
5. **Code generator.** `codegen/src/hassette_codegen/sync_facade/generic.py` emits imports of moved names at lines ~38, 95, 104, 184, 232, 239, 315 (e.g. `from hassette.types.types import LOG_LEVEL_TYPE, IfExistsPolicy, WhereClause`). Change the emitted text so moved names come from `hassette_wire` and non-moved names keep their line. Regenerate with the four prek hooks: `prek run generate_sync_facade generate_recording_sync_facade generate_bus_sync_facade generate_scheduler_sync_facade -a`, and confirm the generated `sync.py` files match what the import rewrite produced (no diff after regeneration beyond what you intend).
6. **Docs.** `docs/pages/core-concepts/internals/lifecycle.md` (1 occurrence) and `docs/pages/core-concepts/bus/methods.md` (2 occurrences): `[hassette.types.enums.ResourceStatus]` → `[hassette.ResourceStatus]`. `docs/pages/testing/snippets/testing_simulate_service_failure.py`: `from hassette import ResourceStatus`. `mkdocs.yml`: add `wire/src` to the mkdocstrings python handler `paths`. `tools/docs/check_xref_coverage.py:69`: map `"ResourceStatus"` to `"hassette.ResourceStatus"`. `src/hassette/cli/output.py` ~line 270 docstring: `:class:`~hassette.types.types.CliFormat`` → `:class:`~hassette_wire.CliFormat``.
7. **Test.** Create `tests/unit/test_wire_public_paths.py`: assert `hassette.ExecutionMode is hassette_wire.ExecutionMode` (and the same for `BackpressurePolicy`, `ResourceStatus`, `ExecutionStatus`), and that no FR#5/FR#6 name (the ten names above minus CliFormat/CliFormatStyle, which AC#2 covers in T03) is an attribute of `hassette.types`, `hassette.types.enums`, `hassette.types.types`, or `hassette.schemas`. T03 extends this file with AC#2.

## Focus
- **Split imports.** Several import statements mix moved names with `DEFAULT_OVERLAP_MODE`/`DEFAULT_BACKPRESSURE_POLICY`, which stay in `hassette.types.enums`. Examples: `src/hassette/schemas/listener_models.py:15`, `src/hassette/schemas/job_models.py:15`, `src/hassette/core/registration.py:5`, `src/hassette/web/models.py:13` (multi-line), `tests/support/web_telemetry_helpers.py:8`, `tests/support/factories.py:38`. The rewrite must split each one into a `hassette_wire` import for the moved names and a remaining `hassette.types.enums` import for the constants. It must not move the constants, and it must not drop the enums.
- Blast radius is ~150 files; all current imports are absolute (`from hassette.types...`) except `src/hassette/__init__.py` (`from .types.enums import …`) and `src/hassette/types/__init__.py` (`from .enums import (…)`, `from .types import (…)`).
- `src/hassette/web/models.py` and `src/hassette/schemas/*.py` also import these names — rewrite them here too so the tree stays green; T02 then moves those files' contents.
- Wire models that default to `DEFAULT_OVERLAP_MODE`/`DEFAULT_BACKPRESSURE_POLICY` are handled in T02, not here; in this task those constants simply import their enums from `hassette_wire`.
- `hassette_wire` must not import `hassette` (FR#10, enforced in T02's isolation test) — `cli_format.py` must not pull in anything from `hassette.cli`.
- The generated sync facades (`src/hassette/api/sync.py`, `bus/sync.py`, `scheduler/sync.py`, and the recording facade) are regenerated by prek hooks whose `files` patterns include `codegen/src/hassette_codegen/sync_facade/`; a mismatch between generator text and the rewritten files makes the hook rewrite them on the next commit.
- `tests/unit/tools/test_generate_sync_facade.py` may assert on emitted header text — update any literal expectations to the new import lines.
- The schemas must stay byte-identical (Dependencies and Assumptions, "Accepted: moving the enums keeps the schemas byte-identical"). Run `uv run python scripts/export_schemas.py --types` (after `cd frontend && npm install` once) and confirm `git diff --exit-code frontend/` is clean. If it isn't, find the cause and fix it (preferred) or explain it in your report.
- `mkdocs build --strict` may take a while; run it once at the end.

## Verify
- [ ] FR#5: `grep -rnE "class (ResourceStatus|ManifestStatus|ExecutionMode|BackpressurePolicy|ExecutionStatus)\b" src wire/src` shows only `wire/src/hassette_wire/enums.py`, and none of those classes contains `auto()`.
- [ ] FR#6: `grep -rnE "^(SourceTier|LOG_LEVEL_TYPE|QuerySourceTier)\b" src wire/src` shows definitions only in `wire/src/hassette_wire/literals.py`.
- [ ] FR#7: `uv run python -c "import hassette, hassette_wire as w; assert all(getattr(hassette, n) is getattr(w, n) for n in ['ExecutionMode','BackpressurePolicy','ResourceStatus','ExecutionStatus']); assert {'ResourceStatus','ExecutionStatus'} <= set(hassette.__all__)"` exits 0.
- [ ] FR#8: `CliFormat`/`CliFormatStyle` are defined only in `wire/src/hassette_wire/cli_format.py`, and `src/hassette/cli/output.py` imports `CliFormat` from `hassette_wire`.
- [ ] AC#3: `uv run pytest tests/unit/test_wire_public_paths.py -n 4` passes.
- [ ] AC#12: `uv run pytest tests/unit/cli -n 4` passes, including the `test_output*` tests that render `CliFormat`-annotated fields humanized.
- [ ] AC#13: `uv run mkdocs build --strict` succeeds.

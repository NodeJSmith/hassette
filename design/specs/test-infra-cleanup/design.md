# Design: Test Infrastructure Deduplication & LLM Prevention

**Date:** 2026-07-08
**Status:** Draft
**Research:** `design/research/2026-07-08-llm-test-infra-duplication/research.md` (prior art); audit reports in session scratchpad (conftest hierarchy, test_utils package, test data, cross-cutting duplication)

## Problem

The test infrastructure has accumulated duplication debt: ~130 local `make_*/build_*` factory functions scattered across 400 test files, while `test_utils/factories.py` (built specifically to absorb them) holds only 3 factories. The same conceptual object (`ScheduledJob`, `Event`, `CommandExecutor` mock) is built 4-11 different ways across sibling files. Factory names are overloaded — `make_job` and `make_manifest` each mean 2-3 different return types depending on which file you're in.

This duplication is not historical accident — it's the predictable result of LLM-assisted development. GitClear's analysis of 211M+ lines shows AI-era code duplication up 4x and reuse down 70%. The project's test infrastructure has no structural prevention: CLAUDE.md points to TESTING.md (a two-hop discovery chain), no `.claude/rules/` file addresses test writing, and no lint rule catches factory reinvention. An LLM that doesn't read TESTING.md — or whose context fills before reaching it — has nothing stopping it from creating yet another `make_job()`.

Prior specs (039, 040, 061) addressed structural harness issues (exception swallowing, startup ordering, mock consolidation). This spec addresses the duplication layer and the prevention layer.

## Goals

1. Consolidate the 5 worst factory duplication hotspots into shared, override-friendly factories in `test_utils/factories.py`
2. Delete confirmed dead code (13 test app files, 4 dead test_utils exports, 1 dead fixture, 1 stale event file, 6 dead asyncio markers)
3. Fix misplaced fixtures and naming collisions identified by the audit
4. Establish a `.claude/rules/test-conventions.md` that closes the two-hop discovery gap
5. Add CLAUDE.md files to key test directories with module-specific fixture pointers
6. Write a `tools/check_test_factories.py` linter that catches future factory reinvention
7. Document decision rules in TESTING.md for `make_mock_hassette` vs `create_hassette_stub` and the `make_*/create_*/build_*` naming convention

## Non-Goals

- Restructuring `harness.py` (820 lines) — worth doing but a separate scope
- Splitting `recording_api.py` or making its CRUD methods table-driven — codegen territory
- Changing test directory structure or co-locating tests with source
- Addressing the pre-existing Python 3.14 async mock failures (separate issue)

## Phases

### Phase 1: Delete Dead Code

Remove confirmed-dead items. No behavior change, no callers to update.

**Files to delete:**
- 13 test app files in `tests/data/apps/` (verified: full test suite passes without them)
- `tests/data/events/device_tracker_event.json` (wrong format, zero references)

**Code to delete:**
- `emit_service_event()` from `test_utils/helpers.py:408` and its re-exports in `_internal/__init__.py` and `__init__.py`
- `make_listener_metric()` from `test_utils/web_helpers.py:146` and its re-exports
- `setup_registry()` from `test_utils/web_helpers.py:194` and its re-exports
- `hassette_with_nothing` fixture from `test_utils/fixtures.py:54`
- `mock_transport_builder` fixture from `tests/unit/cli/conftest.py:148`
- Remove stale TESTING.md references to deleted items

**Markers to remove:**
- Dead `@pytest.mark.asyncio` markers in 6 files (no-op under `asyncio_mode = "auto"`)

### Phase 2: Consolidate Factory Hotspots

Add 5 shared factories to `test_utils/factories.py`, migrate callers, delete local duplicates.

**New factories:**

| Factory | Returns | Replaces | Local definitions |
|---|---|---|---|
| `make_scheduled_job(**overrides)` | `ScheduledJob` | 11 local `make_job()` variants | `tests/unit/` and `tests/unit/core/` |
| `make_mock_executor()` | `MagicMock` with `execute=AsyncMock()` | 4 byte-identical `make_executor()` | `tests/unit/core/` and `tests/unit/bus/` |
| `make_mock_event(topic=..., payload=None)` | `MagicMock(spec=Event)` or `Event(...)` | 6 local `make_event()` + generic event construction | `tests/unit/core/` and `tests/unit/bus/` |
| `make_recording_api(hassette=None, state_proxy=None)` | `RecordingApi` | 3 near-identical local factories | `tests/unit/test_recording_*.py` |
| `make_hassette_event(topic=..., data=None)` | `Event` with `HassettePayload` | 2 byte-identical locals | `tests/unit/core/` |

**Also fix:**
- `make_invoke_handler_cmd` shadow in `test_command_executor_execution_id.py:53` — delete local, import shared
- Add `autostart` parameter to `web_helpers.make_manifest()` — delete local duplicate in `test_mappers.py:144`
- Consolidate `make_mock_parent()` into one helper (currently built 3 separate times)

**Naming disambiguation:**
- Rename `web_helpers.make_job()` → `make_job_namespace()` (returns `SimpleNamespace`, not `ScheduledJob`)
- Consider `make_manifest()` → `make_manifest_info()` in `web_helpers.py` (returns `AppManifestInfo`, not `AppManifest`)

### Phase 3: Fix Misplacement and Naming

**Fixture misplacement:**
- Move `app`, `client`, `runtime_query_service` from `tests/integration/conftest.py` to `tests/integration/web_api/conftest.py` (they depend on `mock_hassette` which only exists there)
- Move `noop()` from `tests/unit/scheduler/conftest.py` to `test_utils/helpers.py` (used by 13 files including integration tests)

**Naming collisions:**
- Rename `tests/unit/conftest.py::make_test_config` → `make_sync_executor_config` (collides with public `test_utils.config.make_test_config`)
- Document (or rename) the `hassette_with_bus` shadow in `tests/unit/bus/conftest.py` — add a docstring explaining the intentional scope/type override, following the pattern of `telemetry/conftest.py::db_hassette`

**Naming consistency:**
- Standardize `make_mock_` prefix for mock-object factories vs `make_` for real-object factories vs `create_` for complex multi-step construction (document in TESTING.md)

### Phase 4: LLM Prevention Layer

**`.claude/rules/test-conventions.md`:**
- Names the canonical test infrastructure: `test_utils/factories.py`, `test_utils/helpers.py`, `test_utils/web_helpers.py`
- Links directly to the TESTING.md decision table (closes the two-hop gap)
- Explicit prohibition: "Before defining a local `make_*` or `build_*` function in a test file, check `test_utils/factories.py` and `test_utils/helpers.py` for an existing factory"
- Names the `make_mock_hassette()` vs `create_hassette_stub()` decision rule
- Lists the 10 most-used test_utils symbols with import paths

**CLAUDE.md files in test directories:**
- `tests/unit/bus/CLAUDE.md` — names `hassette_with_bus` (local override, function-scoped, yields `Hassette`), `bus/helpers.py`, `bus/conftest.py::mock_add_listener`
- `tests/unit/core/CLAUDE.md` — names `make_executor`, `make_bus_service`, `make_watcher` conftest helpers, telemetry fixtures
- `tests/integration/bus/CLAUDE.md` — names `bus_harness` fixture, `bus/helpers.py`
- `tests/integration/web_api/CLAUDE.md` — names `mock_hassette`, `app`, `client` fixtures
- `tests/integration/telemetry/CLAUDE.md` — names `db_hassette` override, `telemetry/helpers.py`
- Keep each under 20 lines — module-specific pointers only, universal guidance lives in the rule file

**`tools/check_test_factories.py` linter:**
- Pre-commit hook that scans test files for local `def make_*` / `def build_*` definitions
- Compares against a registry of shared factories in `test_utils/factories.py`, `test_utils/helpers.py`, `test_utils/web_helpers.py`
- Flags when a local factory name matches (or closely matches) a shared factory name
- Exemption mechanism for legitimately local factories (comment annotation or allowlist)
- Wired into `.pre-commit-config.yaml` alongside existing `check_*.py` linters

### Phase 5: Documentation

**TESTING.md updates:**
- Remove references to deleted items (`make_listener_metric`, `setup_registry`, `hassette_with_nothing`)
- Add decision rule: when to use `make_mock_hassette()` vs `create_hassette_stub()` (currently undocumented)
- Add naming convention: `make_mock_*` for mock objects, `make_*` for real objects, `create_*` for complex construction
- Document the `TEST_*` vs `STUB_*` constant distinction
- Add a "Before writing a new factory" checklist pointing to `factories.py`

## Sequencing

Phases 1-3 are the cleanup (fixing what the audit found). Phases 4-5 are prevention (stopping recurrence). The linter in Phase 4 requires Phase 2 to be complete (shared factories must exist before the linter can point to them).

| Phase | Depends on | Effort | Risk |
|---|---|---|---|
| 1. Delete dead code | — | ~1 hour | Near-zero (verified by test suite) |
| 2. Consolidate factories | — | ~4 hours | Low (mechanical, each migration is independently testable) |
| 3. Fix misplacement/naming | — | ~2 hours | Low (fixture moves are testable) |
| 4. LLM prevention layer | Phase 2 | ~3 hours | Low (additive — rule file, CLAUDE.md files, linter) |
| 5. Documentation | Phases 1-3 | ~1 hour | Near-zero |

Total: ~11 hours of work, all independently landable phases.

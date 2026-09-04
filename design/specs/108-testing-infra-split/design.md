# Design: Separate Public and Internal Testing Infrastructure

**Date:** 2026-09-02
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-09-02-testing-infra-split/research.md

## Problem

App authors writing hassette automations cannot distinguish which test helpers are supported public API vs internal framework plumbing. The module name `test_utils` reads as repository tooling, and 76 symbols are importable from the root even though only 17 are in `__all__`. The public API (`AppTestHarness`, `RecordingApi`, `HassetteHarness`, etc.) is tangled with internal-only helpers (web-layer factories, seed scenario infrastructure, codegen templates) in a single namespace with no structural boundary. Three downstream issues in the Testing API Redesign milestone are hard-blocked on this restructuring.

## Goals

- `hassette.testing` is the sole public test API namespace, with a clear `__all__` defining the supported surface.
- Tier 2 internal helpers (web-layer factories, seed scenario infrastructure, codegen-only modules) live in `tests/support/`, outside `src/` and absent from the wheel. Private implementation modules that the public API transitively depends on (`_harness.py`, `_simulation.py`, etc.) remain in the wheel as `_`-prefixed modules — the structural boundary is namespace clarity and `__all__`, not wheel size reduction.
- `hassette.test_utils` no longer exists — not as a package, not as a re-export shim.
- A wheel smoke test verifies the boundary: `from hassette.testing import AppTestHarness` works, `import hassette.test_utils` raises `ModuleNotFoundError`.
- All existing tests pass with the new import paths.

## Non-Goals

- API redesign of any helper (just a location change, not a behavior change).
- External consumer migration (handled in a separate effort).
- Downstream Testing API Redesign milestone issues (#1347–#1359).
- A separately versioned `hassette-testing` package.
- Preserving any import path into `hassette.test_utils` via shim or deprecation warning.

## User Scenarios

### App Author: Writing tests for a hassette automation

- **Goal:** Import test harness and event factories to test their app
- **Context:** Working in their own repo, hassette installed as a dependency

#### Test a state-change handler

1. **Add `hassette.testing` to pytest_plugins or import directly**
   - Sees: `hassette.testing` in IDE autocomplete, clean namespace with only public helpers
   - Decides: which helpers to import (AppTestHarness, event factories, etc.)
   - Then: writes test using the public API

### Hassette Contributor: Working on framework internals

- **Goal:** Use the full internal test infrastructure to test framework changes
- **Context:** Working inside the hassette repo, running `uv run pytest`

#### Test a bus registration edge case

1. **Import from `hassette.testing` or `tests.support`**
   - Sees: `hassette.testing` for public API (including `HassetteHarness`, `wait_for`), `tests.support` for internal-only helpers (web stubs, factories, etc.)
   - Decides: which helpers to use, importing Tier 1 from `hassette.testing` and Tier 2 from `tests.support` or `hassette.testing._*` private modules
   - Then: writes test using internal infrastructure, discovered via `pytest_plugins` for fixtures

## Functional Requirements

- **FR#1** `from hassette.testing import X` succeeds for every symbol in the Tier 1 set (see Architecture for the complete list).
- **FR#2** `from hassette.testing import X` raises `ImportError` for every symbol not in `__all__`. Note: some non-`__all__` symbols ship in the wheel as private modules (e.g., `SimpleTestServer` in `_server.py`, `build_fake_ws` in `_ws_mocks.py`) — they are importable via `hassette.testing._<module>` but not via `hassette.testing` directly. True Tier 2 symbols (e.g., `make_mock_hassette`) are absent from the wheel entirely.
- **FR#3** `import hassette.test_utils` raises `ModuleNotFoundError` after the migration.
- **FR#4** `hassette.testing.__all__` contains exactly the Tier 1 symbols and no others.
- **FR#5** All pytest fixtures currently registered via `hassette.test_utils.fixtures` and `hassette.test_utils.resource_tracker` remain discoverable within hassette's own test suite after migration. Tier 1 fixtures (`dummy_cache`, `event_capture`) remain discoverable by external consumers via `hassette.testing.fixtures`. Tier 2 fixtures are internal-only (`tests.support.fixtures`, rootdir-based resolution).
- **FR#6** The dependency direction is one-way: `hassette.testing` imports nothing from `tests.support`; `tests/support/` may import from `hassette.testing`.
- **FR#7** The built wheel contains the `hassette/testing/` package and does not contain `hassette/test_utils/`.
- **FR#8** Tier 1 pytest fixtures (`dummy_cache`, `event_capture`) ship in the wheel via `hassette.testing.fixtures` and are registerable by app authors.
- **FR#9** Tier 2 pytest fixtures (`hassette_harness`, `hassette_with_*`, etc.) are registered via `tests.support.fixtures` and are not in the wheel.

## Edge Cases

- **Mixed-tier multi-line imports** — `from hassette.test_utils import (X, Y)` where X is Tier 1 and Y is Tier 2. The codemod must split these into two separate import statements targeting `hassette.testing` and `tests.support` respectively.
- **Private implementation modules** — `_simulation.py` uses `create_component_loaded_event` and `create_service_registered_event`. These two ~16-line functions are folded directly into `_simulation.py` to avoid creating an extra private module. Test files that also use them import from `tests.support.helpers`, which re-exports them from `hassette.testing._simulation`.
- **`pytest_plugins` resolution mechanism change** — moving from installed-package paths (`hassette.test_utils.fixtures`) to a mix of installed-package (`hassette.testing.fixtures`) and rootdir-based (`tests.support.fixtures`). The rootdir mechanism already works for `tests.coverage_integrity`.
- **conftest.py cascade** — 14 conftest files import from test_utils. A broken conftest propagates to every test in its scope.
- **Circular imports** — `hassette.testing` must be self-contained. `tests/support/` may import from `hassette.testing` but not vice versa.
- **String reference misses** — `pytest_plugins` entries, tool scripts, markdown docs, and CLAUDE.md contain string references to `hassette.test_utils` that an AST-based codemod cannot catch. These require a separate grep-and-fix pass.

## Acceptance Criteria

- **AC#1** `uv run nox -s dev` passes with zero test failures after the migration. (Verifies FR#1, FR#2, FR#5)
- **AC#2** `prek -a` passes (lint + type check). (Verifies all FRs for static correctness)
- **AC#3** A nox `wheel_smoke` session builds the wheel, installs it in an isolated venv, verifies `from hassette.testing import AppTestHarness` succeeds, and `import hassette.test_utils` raises `ModuleNotFoundError`. (Verifies FR#3, FR#7)
- **AC#4** `hassette.testing.__all__` matches the expected Tier 1 symbol set (verified by updated `test_public_api_surface.py`). (Verifies FR#4)
- **AC#5** `grep -r "hassette.test_utils" src/ tests/ tools/ docs/ scripts/ codegen/ .claude/ prek.toml ruff.toml` returns zero matches. (Verifies complete migration)
- **AC#6** `grep -r "from tests.support" src/hassette/testing/` returns zero matches, AND `tools/check_module_boundaries.py` includes a new `testing-isolation` rule that AST-checks the same invariant (catches `import tests.support.*` forms the grep misses). (Verifies FR#6)

## Key Constraints

- **No shim period.** Every `hassette.test_utils` import must be rewritten in the same PR. No temporary re-exports, no deprecation warnings, no compatibility layer.
- **Codemod is throwaway.** The libcst migration script and symbol manifest are working tools, not committed artifacts. Only the results land in the PR.
- **One-way dependency.** `hassette.testing/` must never import from `tests/support/`. Any helper that `hassette.testing/` needs internally stays inside `hassette.testing/` as a private (`_`-prefixed) module.
- **Breaking change.** This PR ships as `feat!:` (or `refactor!:`) with a `BREAKING CHANGE:` footer in the PR body enumerating the old→new mapping for every symbol the external consumer is known to use, plus the general `hassette.test_utils` removal. Required by `.claude/rules/changelog-quality.md`.

## Dependencies and Assumptions

- **libcst** must be added as a dev dependency for the migration codemod. It is not a permanent runtime dependency.
- **Downstream milestone sequencing.** This PR must merge before any of the nine non-blocked Testing API Redesign milestone issues begin work, since those issues touch files this PR moves. This is a coordination concern, not an AC — it cannot be verified locally.
- **External consumer exists.** An external consumer uses both Tier 1 and Tier 2 helpers. Its migration is out of scope for this PR but must happen before the next hassette release that drops `test_utils`.

## Architecture

### Module mapping (authoritative)

The table below is the authoritative reference for where each source module ends up. Every symbol defined in a source module moves to its destination module — the codemod derives its symbol manifest from the actual source files using this table, not from the representative symbol lists in the layout sections below.

**Rule:** Tier 1 symbols (those in `__all__`) go to `hassette.testing`. All other symbols go to `tests/support`. When a source module contains both tiers, it splits: Tier 1 symbols to the `hassette.testing` destination, Tier 2 symbols to the `tests/support` destination.

**Transitive dependency rule:** Any module that a Tier 1 public symbol transitively imports at the module level must ship in the wheel. These modules become private (`_`-prefixed) modules in `hassette.testing/`. The module mapping table below is the single source of truth for which modules go where — it was computed by tracing the full import graph from each Tier 1 entry point. The codemod reads this table mechanically; it does not recompute the closure. If the source files change between design approval and implementation, the table must be updated to match before the codemod runs.

| Source module | Tier 1 destination (`hassette.testing/`) | Tier 2 destination (`tests/support/`) |
|---|---|---|
| `app_harness.py` | `app_harness.py` | — |
| `recording_api.py` | `recording_api.py` | — |
| `api_call.py` | `api_call.py` | — |
| `config.py` | `config.py` (entire file — `make_test_config` uses `TEST_TOKEN` etc. internally) | — (tests import from `hassette.testing.config` directly) |
| `exceptions.py` | `exceptions.py` | — |
| `event_capture.py` | `event_capture.py` | — |
| `fixtures.py` | `fixtures.py` (`dummy_cache`, `event_capture`, `build_harness`) | `fixtures.py` (remaining: `hassette_harness`, `hassette_with_*`, etc.) |
| `harness.py` | `_harness.py` (entire file except `preserve_config` — private) | `harness.py` (owns `preserve_config` only) |
| `simulation.py` | `_simulation.py` (entire file — private) | — (tests import from `hassette.testing._simulation` directly) |
| `time_control.py` | `_time_control.py` (entire file — private) | — (tests import from `hassette.testing._time_control` directly) |
| `sync_facade.py` | `_sync_facade.py` (entire file — private) | — (tests import from `hassette.testing._sync_facade` directly) |
| `helpers.py` | `_factories.py` (Tier 1 factories: 8 symbols in `__all__`) | `helpers.py` (all remaining symbols) |
| `helpers.py` (2 event builders used by `_simulation.py`) | folded into `_simulation.py` directly | `helpers.py` (re-exports from `hassette.testing._simulation`) |
| `factories.py` | — | `factories.py` (entire file) |
| `mock_hassette.py` | — | `mock_hassette.py` (entire file) |
| `web_mocks.py` | — | `web_mocks.py` (entire file) |
| `web_manifest_helpers.py` | — | `web_manifest_helpers.py` (entire file) |
| `web_job_helpers.py` | — | `web_job_helpers.py` (entire file) |
| `web_response_helpers.py` | — | `web_response_helpers.py` (entire file) |
| `web_telemetry_helpers.py` | — | `web_telemetry_helpers.py` (entire file) |
| `ws_mocks.py` | `_ws_mocks.py` (entire file — private; `_harness.py` uses `configure_ready_websocket_mock`) | — (tests import from `hassette.testing._ws_mocks` directly) |
| `sql_helpers.py` | — | `sql.py` (entire file) |
| `test_server.py` | `_server.py` (entire file — private; `_harness.py` uses `SimpleTestServer`) | — (tests import from `hassette.testing._server` directly) |
| `uvicorn_server.py` | — | `uvicorn.py` (entire file) |
| `reset.py` | `_reset.py` (entire file — private; `_harness.py` imports reset functions) | — (tests import from `hassette.testing._reset` directly) |
| `resource_tracker.py` | — | `resource_tracker.py` (entire file) |
| `state_proxy_mocks.py` | — | `state_proxy_mocks.py` (entire file) |

### Package layout: `hassette.testing`

Ships in the wheel. Contains Tier 1 public API and private implementation modules that the public API depends on. Symbol lists below are representative — see the module mapping table above for the authoritative file-level routing.

```
src/hassette/testing/
    __init__.py          # re-exports Tier 1 symbols, defines __all__
    app_harness.py       # AppTestHarness, AppConfigurationError
    recording_api.py     # RecordingApi, RecordingHelperClient
    api_call.py          # ApiCall
    config.py            # make_test_config
    exceptions.py        # DrainError, DrainFailure, DrainTimeout
    event_capture.py     # EventCapture (promoted from Tier 2)
    fixtures.py          # Tier 1 fixtures: dummy_cache, event_capture
                         # Tier 1 context manager: build_harness
    _simulation.py       # SimulationMixin (private, AppTestHarness depends on it)
    _time_control.py     # TimeControlMixin (private, AppTestHarness depends on it)
    _sync_facade.py      # RecordingSyncFacade (private, RecordingApi depends on it)
    _harness.py          # HassetteHarness and all its dependencies (private;
                         #   AppTestHarness._setup() depends on it)
    _reset.py            # Reset functions (private; _harness.py imports them)
    _server.py           # SimpleTestServer (private; _harness.py uses it)
    _ws_mocks.py         # WS mock helpers (private; _harness.py uses
                         #   configure_ready_websocket_mock)
    _factories.py        # Tier 1 factory functions from helpers.py
```

### Package layout: `tests/support`

Does not ship in the wheel. Lives outside `src/` and is invisible to `uv_build`. Contains all Tier 2 internal helpers organized by domain. Symbol lists below are representative — see the module mapping table for the authoritative file-level routing.

```
tests/support/
    __init__.py
    harness.py           # preserve_config only
    fixtures.py          # All Tier 2 fixtures
    factories.py         # All Tier 2 factories from current factories.py
    helpers.py           # All Tier 2 helpers from current helpers.py;
                         #   re-exports _simulation.py event builders for test convenience
    mock_hassette.py     # make_mock_hassette (demoted from Tier 1), make_ws_hassette_stub
    web_mocks.py         # All symbols from current web_mocks.py
    web_manifest_helpers.py  # All symbols from current web_manifest_helpers.py
    web_job_helpers.py   # All symbols from current web_job_helpers.py
    web_response_helpers.py  # All symbols from current web_response_helpers.py
    web_telemetry_helpers.py # All symbols from current web_telemetry_helpers.py
    sql.py               # All symbols from current sql_helpers.py
    uvicorn.py           # All symbols from current uvicorn_server.py
    resource_tracker.py  # ResourceTracker, pytest hooks
    state_proxy_mocks.py # All symbols from current state_proxy_mocks.py
```

### Tier 1 symbol set (`hassette.testing.__all__`)

The 21 symbols that form the public API (demoting `make_mock_hassette`, promoting `EventCapture`, `HassetteHarness`, `wait_for`, `build_harness`, `make_full_state_change_event`):

```python
__all__ = [
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "DrainError",
    "DrainFailure",
    "DrainTimeout",
    "EventCapture",
    "HassetteHarness",
    "RecordingApi",
    "build_harness",
    "create_call_service_event",
    "create_state_change_event",
    "dummy_cache",
    "make_full_state_change_event",
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
    "make_typed_state",
    "wait_for",
]
```

Note: `dummy_cache` appears both as an importable symbol (in `__all__`) and as a pytest fixture in `hassette.testing.fixtures`. `EventCapture` is the importable class (in `__all__`); `event_capture` is the lowercase pytest fixture name in `hassette.testing.fixtures` that yields an `EventCapture` instance — the fixture name is not in `__all__`.

### `pytest_plugins` registration change

`tests/conftest.py` changes from:

```python
pytest_plugins = [
    "hassette.test_utils.fixtures",
    "hassette.test_utils.resource_tracker",
    "tests.coverage_integrity",
]
```

To:

```python
pytest_plugins = [
    "hassette.testing.fixtures",
    "tests.support.fixtures",
    "tests.support.resource_tracker",
    "tests.coverage_integrity",
]
```

`hassette.testing.fixtures` is an installed-package path (same mechanism as before). `tests.support.fixtures` uses rootdir-based resolution (same mechanism as the existing `tests.coverage_integrity` entry).

### Codemod strategy

A throwaway libcst-based codemod (not committed) rewrites all ~490 `from hassette.test_utils...` import statements. It reads a JSON symbol manifest mapping each symbol to its new module path. The transform is deterministic: each symbol maps to exactly one new location.

**Import transformation rules:**

| Current import path | New import path |
|---|---|
| `from hassette.test_utils import <Tier1Symbol>` | `from hassette.testing import <Tier1Symbol>` |
| `from hassette.test_utils.<tier1_module> import <Tier1Symbol>` | `from hassette.testing import <Tier1Symbol>` |
| `from hassette.test_utils import <Tier2Symbol>` | `from tests.support.<module> import <Tier2Symbol>` |
| `from hassette.test_utils.<tier2_module> import <Tier2Symbol>` | `from tests.support.<module> import <Tier2Symbol>` |
| `from hassette.test_utils.<private_module> import <Symbol>` (where module maps to `hassette.testing._*`) | `from hassette.testing._<module> import <Symbol>` |

Mixed-tier multi-line imports are split into two separate import statements. The codemod runs as a dry-run first, and the full test suite validates the result.

### String reference cleanup

A separate grep pass after the codemod handles non-Python references:

| File | Reference type |
|---|---|
| `tests/conftest.py` | `pytest_plugins` entries |
| `tools/check_test_factories.py` | 37 hardcoded module paths in `SHARED_FACTORIES` |
| `tools/check_module_boundaries.py` | 13 references |
| `docs/pages/testing/index.md` | Import path references in prose |
| `docs/pages/testing/factories.md` | Import path references in prose |
| `docs/pages/migration/testing.md` | Migration guide references in prose |
| `docs/pages/testing/snippets/*.py` (35 files) | Real Python imports — AST-rewritable |
| `docs/pages/migration/snippets/*.py` (2 files) | Real Python imports — AST-rewritable |
| `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py` | Real Python import |
| `scripts/seed_scenarios/base.py`, `degraded.py` | Real Python imports from `hassette.test_utils.factories` |
| `codegen/src/hassette_codegen/sync_facade/recording.py` | Embedded import in code-generation template |
| `codegen/src/hassette_codegen/sync_facade/cli.py` | Hardcoded default paths to `src/hassette/test_utils/` |
| `prek.toml` | `generate_recording_sync_facade` hook `files` regex references `test_utils/recording_api\.py`; `check-module-boundaries` hook `name:` string contains `test_utils` (update description) |
| `ruff.toml` | Per-file-ignore keyed on `src/hassette/test_utils/*.py`; may need a new per-file-ignore for `tests/support/*.py` and `tests/**` importing `hassette.testing._*` private modules |
| `docs/pages/core-concepts/cache/index.md` | Prose reference to `hassette.test_utils`/`dummy_cache` |
| `docs/document-codegen.md` | Prose reference to `src/hassette/test_utils/recording_api.py` |
| `tools/docs/gen_ref_pages.py` | Hardcoded `hassette.test_utils` module path and nav link |
| `tests/TESTING.md` | 29 references |
| `.claude/rules/test-conventions.md` | ~20 references |

## Implementation Preferences

- **Codemod:** `libcst` for AST-based import rewriting. Added as a dev dependency, used for the throwaway migration tool only.
- **Package structure:** Standard `__init__.py` with explicit `__all__`, matching the existing pattern in `test_utils/__init__.py`.
- **Private modules:** `_`-prefixed modules in `hassette.testing/` for implementation that the public API depends on but app authors should not import directly.

## Replacement Targets

- **`src/hassette/test_utils/`** — the entire package is replaced by `src/hassette/testing/` (Tier 1 symbols) and `tests/support/` (Tier 2 internals). Delete after migration; do not preserve alongside the new structure.

## Convention Examples

### `__all__` with tier comment

**Source:** `src/hassette/test_utils/__init__.py:91-110`

```python
__all__ = [
    # Tier 1 only
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    # ... remaining symbols
]
```

New `hassette.testing/__init__.py` follows the same shape with `__all__` defining the public surface.

### Pytest plugin registration

**Source:** `tests/conftest.py:58-65`

```python
pytest_plugins: list[str] = [
    "hassette.test_utils.fixtures",
    "hassette.test_utils.resource_tracker",
    "tests.coverage_integrity",
]
```

The existing `tests.coverage_integrity` entry demonstrates rootdir-based resolution already working. New `tests.support.fixtures` uses the same mechanism.

### Public API surface test

**Source:** `tests/unit/test_public_api_surface.py`

```python
TIER1_SYMBOLS = {
    "ApiCall",
    "AppConfigurationError",
    # ...
}

def test_tier1_in_all() -> None:
    assert set(test_utils.__all__) == TIER1_SYMBOLS
```

Updated to verify `hassette.testing.__all__` instead.

## Alternatives Considered

**Option B: `hassette._test_internals`** — Keep Tier 2 internals in the installed package under an underscore-prefixed name. Simpler mechanically (no pytest path-resolution change), but does not satisfy the acceptance criteria: internal test code still ships in the wheel (~5,000 lines), and the `_` prefix is a weaker signal than physical absence. Users can and will autocomplete into it. Rejected because it leaves the wheel-hygiene motivation unaddressed.

## Test Strategy

### Required Test Types

Unit tests only. This is a pure restructuring with no behavior change — the existing test suite IS the test. If all 445 imports are migrated correctly and the tests pass, the migration is correct.

### Existing Tests to Adapt

- `tests/unit/test_public_api_surface.py` — update to verify `hassette.testing.__all__` instead of `hassette.test_utils.__all__`. Update `TIER1_SYMBOLS` set to reflect: `make_mock_hassette` demotion, `EventCapture`/`HassetteHarness`/`wait_for`/`build_harness` promotions. The existing `test_tier2_not_in_all` test explicitly asserts `HassetteHarness` and `wait_for` are NOT in `__all__` — these assertions must be flipped or removed since both are now Tier 1. The `test_tier2_importable` test asserts `HassetteHarness` is importable from `hassette.test_utils` as a Tier 2 symbol — this test's premise is invalidated (it's now Tier 1 importable from `hassette.testing`) and must be rewritten.
- All ~260 test files with `hassette.test_utils` imports — import paths updated by the codemod.
- 14 `conftest.py` files importing from `hassette.test_utils` — import paths updated.

### New Test Coverage

- **Wheel smoke test** (AC#3) — new nox session `wheel_smoke` that builds, installs, and verifies the package boundary. Covers FR#3, FR#7.
- **Tier 2 exclusion test** — verify that `hassette.testing` does not export Tier 2 symbols (FR#2). Added to the updated `test_public_api_surface.py`.

### Tests to Remove

No tests to remove. `test_public_api_surface.py` is updated, not removed.

## Smoke Test

**Verification surface:** nox session output, pytest exit code.

**Scenario:** After the migration, run `uv run nox -s dev` and observe all tests pass. Then run the `wheel_smoke` nox session and observe it reports success — `hassette.testing` importable, `hassette.test_utils` raises `ModuleNotFoundError`.

**Success:** Both nox sessions exit 0.

## Documentation Updates

- **`docs/pages/testing/index.md`** — update import path references in prose.
- **`docs/pages/testing/factories.md`** — update factory import path references in prose. Remove the `## make_mock_hassette` section entirely (demoted to internal; the external consumer doesn't use it). Delete the corresponding snippet file `docs/pages/testing/snippets/factories_mock_hassette.py` to avoid orphan-snippet CI failure (`tools/docs/check_snippet_orphans.py`).
- **`docs/pages/migration/testing.md`** — update migration guide references in prose.
- **`docs/pages/testing/snippets/*.py`** (35 files) — update real Python imports. These are embedded code snippets included via `--8<--` directives. Pyright is configured with `reportMissingImports: none` for these paths (see `docs/pyrightconfig.json`), so broken imports would not be caught by `prek -a`. The codemod must include these files in its scope.
- **`docs/pages/migration/snippets/*.py`** (2 files) — update real Python imports.
- **`docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py`** — update real Python import. Also requires updating the parent page `docs/pages/core-concepts/api/managing-helpers.md` if it references `hassette.test_utils` in prose.
- **`scripts/seed_scenarios/base.py`**, **`degraded.py`** — update `from hassette.test_utils.factories` imports.
- **`codegen/src/hassette_codegen/sync_facade/recording.py`** — update embedded import in code-generation template from `hassette.test_utils.recording_api` to `hassette.testing.recording_api`. Note `RecordingHelperClient` rides along via the whole-file move of `recording_api.py`.
- **`codegen/src/hassette_codegen/sync_facade/cli.py`** — update hardcoded default paths from `src/hassette/test_utils/` to `src/hassette/testing/`.
- **`prek.toml`** — update `generate_recording_sync_facade` hook `files` regex from `test_utils/recording_api\.py` to `testing/recording_api\.py`.
- **`ruff.toml`** — update per-file-ignore path from `src/hassette/test_utils/*.py` to `src/hassette/testing/*.py`.
- **`docs/pages/core-concepts/cache/index.md`** — update prose reference to `hassette.test_utils`/`dummy_cache`.
- **`docs/document-codegen.md`** — update prose reference to `src/hassette/test_utils/recording_api.py`.
- **`tools/docs/gen_ref_pages.py`** — update hardcoded `hassette.test_utils` module path and nav link to `hassette.testing`.
- **`tests/TESTING.md`** — update 29 references to `hassette.test_utils`.
- **`.claude/rules/test-conventions.md`** — update ~20 references to reflect new module paths and factory locations.

## Impact

<!-- Gap check 2026-09-03: 3 gaps included — codegen/sync_facade/ast_utils.py:24 docstring → T04 string cleanup, .claude/skills/doc-accuracy-review/references/briefing-template.md:53 → T04 string cleanup, .claude/skills/doc-coverage-review/REFERENCE.md:39 → T04 string cleanup -->

### Changed Files

**Shared / cross-cutting (highest risk):**
- modify `tests/conftest.py` — update `pytest_plugins` entries
- modify `tools/check_test_factories.py` — update 37 `SHARED_FACTORIES` path references
- modify `tools/check_module_boundaries.py` — update 13 references
- modify `pyproject.toml` — add `libcst` dev dependency
- modify `.claude/rules/test-conventions.md` — update import paths and factory locations
- modify `tests/TESTING.md` — update 29 references
- modify `scripts/seed_scenarios/base.py` — update `hassette.test_utils.factories` import
- modify `scripts/seed_scenarios/degraded.py` — update `hassette.test_utils.factories` import
- modify `codegen/src/hassette_codegen/sync_facade/recording.py` — update template import
- modify `codegen/src/hassette_codegen/sync_facade/cli.py` — update hardcoded default paths
- modify `prek.toml` — update `generate_recording_sync_facade` hook `files` regex
- modify `ruff.toml` — update per-file-ignore path
- modify `tools/docs/gen_ref_pages.py` — update module path and nav link

**New files:**
- create `src/hassette/testing/__init__.py`
- create `src/hassette/testing/app_harness.py`
- create `src/hassette/testing/recording_api.py`
- create `src/hassette/testing/api_call.py`
- create `src/hassette/testing/config.py`
- create `src/hassette/testing/exceptions.py`
- create `src/hassette/testing/event_capture.py`
- create `src/hassette/testing/fixtures.py`
- create `src/hassette/testing/_simulation.py`
- create `src/hassette/testing/_time_control.py`
- create `src/hassette/testing/_sync_facade.py`
- create `src/hassette/testing/_factories.py`
- create `src/hassette/testing/_harness.py`
- create `src/hassette/testing/_reset.py`
- create `src/hassette/testing/_server.py`
- create `src/hassette/testing/_ws_mocks.py`
- create `tests/support/__init__.py`
- create `tests/support/harness.py`
- create `tests/support/fixtures.py`
- create `tests/support/factories.py`
- create `tests/support/helpers.py`
- create `tests/support/mock_hassette.py`
- create `tests/support/web_mocks.py`
- create `tests/support/web_manifest_helpers.py`
- create `tests/support/web_job_helpers.py`
- create `tests/support/web_response_helpers.py`
- create `tests/support/web_telemetry_helpers.py`
- create `tests/support/sql.py`
- create `tests/support/uvicorn.py`
- create `tests/support/resource_tracker.py`
- create `tests/support/state_proxy_mocks.py`

**Deleted files:**
- delete `src/hassette/test_utils/__init__.py`
- delete `src/hassette/test_utils/api_call.py`
- delete `src/hassette/test_utils/app_harness.py`
- delete `src/hassette/test_utils/config.py`
- delete `src/hassette/test_utils/event_capture.py`
- delete `src/hassette/test_utils/exceptions.py`
- delete `src/hassette/test_utils/factories.py`
- delete `src/hassette/test_utils/fixtures.py`
- delete `src/hassette/test_utils/harness.py`
- delete `src/hassette/test_utils/helpers.py`
- delete `src/hassette/test_utils/mock_hassette.py`
- delete `src/hassette/test_utils/recording_api.py`
- delete `src/hassette/test_utils/reset.py`
- delete `src/hassette/test_utils/resource_tracker.py`
- delete `src/hassette/test_utils/simulation.py`
- delete `src/hassette/test_utils/sql_helpers.py`
- delete `src/hassette/test_utils/state_proxy_mocks.py`
- delete `src/hassette/test_utils/sync_facade.py`
- delete `src/hassette/test_utils/test_server.py`
- delete `src/hassette/test_utils/time_control.py`
- delete `src/hassette/test_utils/uvicorn_server.py`
- delete `src/hassette/test_utils/web_job_helpers.py`
- delete `src/hassette/test_utils/web_manifest_helpers.py`
- delete `src/hassette/test_utils/web_mocks.py`
- delete `src/hassette/test_utils/web_response_helpers.py`
- delete `src/hassette/test_utils/web_telemetry_helpers.py`
- delete `src/hassette/test_utils/ws_mocks.py`

**Modified test files (import paths only):**
- modify ~260 test files — `from hassette.test_utils` → `from hassette.testing` or `from tests.support`
- modify `tests/unit/test_public_api_surface.py` — verify `hassette.testing.__all__`

**Documentation:**
- modify `docs/pages/testing/index.md` — prose import path references
- modify `docs/pages/testing/factories.md` — prose import path references
- modify `docs/pages/migration/testing.md` — prose import path references
- modify `docs/pages/testing/snippets/*.py` (35 files) — real Python imports
- modify `docs/pages/migration/snippets/*.py` (2 files) — real Python imports
- modify `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py` — real Python import
- modify `docs/pages/core-concepts/api/managing-helpers.md` — if it references `hassette.test_utils` in prose
- modify `docs/pages/core-concepts/cache/index.md` — prose reference to `hassette.test_utils`
- modify `docs/document-codegen.md` — prose reference to `test_utils/recording_api.py`

### Behavioral Invariants

- Every existing test must continue passing — no behavior changes, only import path changes.
- `AppTestHarness`, `RecordingApi`, and all Tier 1 helpers must behave identically after the move.
- pytest fixture discovery must work unchanged for both Tier 1 (app authors) and Tier 2 (contributors).

### Blast Radius

- **External consumer** — must update its imports from `hassette.test_utils` to `hassette.testing` and `tests.support` equivalents before upgrading to the hassette version that ships this change. Migration handled separately.
- **Testing API Redesign milestone** — nine issues touch files that this PR moves. Any in-flight branches will need rebasing after merge.
- **Rules files** — `.claude/rules/test-conventions.md` and `tests/TESTING.md` will reflect the new paths, so Claude Code sessions working on hassette will see updated test infrastructure guidance after this lands.

## Open Questions

None — all questions resolved during discovery and blind-spot assessment.

---
proposal: "Separate public testing API (hassette.testing) from internal test infrastructure (tests/support), removing hassette.test_utils"
date: 2026-09-02
status: Draft
flexibility: Leaning
motivation: "External consumers can't distinguish public from internal test helpers; internal-only helpers ship in the wheel; test_utils reads as plumbing, not API"
constraints: "One clean break, no deprecation shim. Rename everything in one PR."
non-goals: "Separately versioned hassette-testing package; preserving undocumented Tier 2 imports; making tests/support user-facing"
depth: normal
---

# Research Brief: Separate Public and Internal Testing Infrastructure (#1333)

**Initiated by**: Issue #1333 -- restructure testing infrastructure to create `hassette.testing` as the sole supported app-author namespace, move internal helpers to `tests/support/`, and remove `hassette.test_utils`.

## Context

### What prompted this

Three drivers apply equally. (1) External app authors cannot tell which test helpers are public API vs internal plumbing -- the module name `test_utils` reads as repository tooling, and 60+ symbols are importable from the root even though only 17 are in `__all__`. (2) This is the anchor issue for the Testing API Redesign milestone; three downstream issues are hard-blocked on it. (3) Internal-only helpers (WebSocket mocks, reset functions, resource trackers, web-layer factories) ship in the published wheel with no exclusion, adding ~5,000 lines of code that no external consumer should touch.

### Current state

`src/hassette/test_utils/` is a 27-file, 8,358-line package. Its `__init__.py` re-exports ~90 symbols at the package root. The boundary between public and internal is enforced by three mechanisms, none of which prevents import:

1. **`__all__` (17 symbols)** -- controls `from hassette.test_utils import *` behavior. These are the Tier 1 public API.
2. **`tests/unit/test_public_api_surface.py`** -- asserts `__all__` matches a hardcoded `TIER1_SYMBOLS` set, and spot-checks that Tier 2 names stay out of `__all__`.
3. **Module docstring** -- states the tier distinction and that Tier 2 "may change without notice."

Eight submodules are never re-exported from `__init__.py` at all (`reset`, `resource_tracker`, `simulation`, `sync_facade`, `time_control`, `web_response_helpers`, `web_telemetry_helpers`, `state_proxy_mocks`) but are imported directly by test files via `from hassette.test_utils.<module> import ...`.

The build backend is `uv_build` with `module-name = "hassette"`. No `exclude` directives exist -- every file under `src/hassette/test_utils/` ships in the wheel. A fresh build of `hassette-0.52.0-py3-none-any.whl` confirms all 27 test_utils files are present.

Pytest fixture discovery is wired through `tests/conftest.py` via `pytest_plugins`:
```python
pytest_plugins = [
    "hassette.test_utils.fixtures",
    "hassette.test_utils.resource_tracker",
    "tests.coverage_integrity",
]
```
This references installed package paths, not relative imports. `tests/` is a proper Python package (has `__init__.py`) and is importable via pytest's rootdir sys.path insertion.

### Key constraints

- **One clean break** -- no deprecation shim, no temporary re-exports with warnings.
- **All changes in one PR** -- every import in every file must be migrated in one shot.
- **Pre-commit hook** -- `tools/check_test_factories.py` hardcodes 38 `hassette.test_utils.*` module paths in its `SHARED_FACTORIES` registry. `tools/check_module_boundaries.py` has 2 references.
- **CLAUDE.md and .claude/rules/test-conventions.md** -- contain extensive documentation of test_utils import paths and factory locations.
- **Docs site** -- `docs/pages/testing/index.md`, `docs/pages/testing/factories.md`, and `docs/pages/migration/testing.md` reference `hassette.test_utils`.
- **tests/TESTING.md** -- 9 references to `hassette.test_utils`.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Create `src/hassette/testing/` | 4-6 new files | Low | Low -- fresh directory, no conflicts |
| Create `tests/support/` | 8-12 files (moved + reorganized) | Med | Med -- reorganization decisions |
| Migrate test imports | 257 test files, 444 import statements | Med | Low -- mechanical, automatable |
| Update `tests/conftest.py` `pytest_plugins` | 1 file, 2 lines | Low | Low -- but load-bearing |
| Update `tools/check_test_factories.py` | 1 file, 38 path references | Low | Low -- mechanical |
| Update `tools/check_module_boundaries.py` | 1 file, 2 references | Low | Low |
| Update docs pages | 3 pages under `docs/pages/` | Low | Low |
| Update `tests/TESTING.md` | 1 file, 9 references | Low | Low |
| Update `.claude/rules/test-conventions.md` | 1 file, ~20 references | Low | Low |
| Update `CLAUDE.md` | 1 file, multiple references | Low | Low |
| Delete `src/hassette/test_utils/` | 27 files | Low | Low -- after migration |
| Add wheel smoke test (nox session) | 1 new nox session | Low | Low |
| Add `uv_build` exclude for `tests/support/` | N/A -- not needed | -- | -- |
| Update `pyproject.toml` build config | 0-1 lines (exclude old test_utils if needed during transition) | Low | Low |

### What already supports this

- **The tier boundary is well-documented.** `__all__` precisely identifies the 17 public symbols. `test_public_api_surface.py` enforces it. The migration plan does not require judgment calls about what is public -- the classification already exists.
- **Submodule-direct imports dominate.** 326 of 444 imports (73%) already use `from hassette.test_utils.<submodule> import X` rather than the root package. A codemod needs to handle two source paths, not one, but both are mechanical.
- **No production code imports test_utils.** Zero imports from `src/hassette/` (outside test_utils itself) or `examples/`. The migration is entirely test-scoped.
- **`tests/` is already a proper Python package.** `tests/__init__.py` exists; `tests.coverage_integrity` is already registered as a pytest plugin. Adding `tests/support/` as a subpackage requires only an `__init__.py`.
- **Pytest's rootdir sys.path insertion** already makes `tests.*` importable without any sys.path manipulation. `tests/support/` will be importable the same way.

### What works against this

- **Scale of mechanical change.** 444 import statements across 257 files is a large diff. The PR will be enormous even though the changes are mechanical. This is the single largest risk -- review fatigue and merge conflicts with concurrent work.
- **14 conftest.py files** import from test_utils. These are load-bearing fixture files; a mistake propagates to every test in their scope.
- **The `pytest_plugins` registration** in `tests/conftest.py` currently uses installed-package paths (`hassette.test_utils.fixtures`). If fixtures move to `tests/support/`, the registration changes to `tests.support.fixtures` -- this still works but the underlying mechanism changes from installed-package resolution to rootdir-based resolution. This is worth testing explicitly.
- **Concurrent milestone work.** Nine other issues in the Testing API Redesign milestone touch the same files that #1333 would move (`app_harness.py`, `recording_api.py`, `sync_facade.py`, `api_call.py`). Any work started on those before #1333 lands will need rebasing. This is a sequencing risk, not a technical one.
- **External consumer.** An external consumer exists that uses both Tier 1 and Tier 2 helpers. Its imports must be migrated alongside the release, but that migration is handled separately from this PR.

## Options Evaluated

### Option A: `hassette.testing` + `tests/support/` + delete `test_utils` (the proposed approach)

**How it works**: Create `src/hassette/testing/` containing only the Tier 1 public API (17 symbols across 4-6 modules). Move all Tier 2 internal helpers to `tests/support/` (organized by domain: harness, fixtures, web mocks, websocket mocks, factories). Delete `src/hassette/test_utils/` entirely. Migrate all 444 imports in one PR using a codemod script.

The `hassette.testing` package ships in the wheel with exactly the public surface. `tests/support/` does not ship -- it sits outside `src/` and is invisible to `uv_build`. The `pytest_plugins` registration in `tests/conftest.py` changes from `"hassette.test_utils.fixtures"` to `"tests.support.fixtures"` (or wherever the internal fixtures land).

**Module layout for `hassette.testing`:**

```
src/hassette/testing/
    __init__.py          # exports the 17 Tier 1 symbols
    app_harness.py       # AppTestHarness, AppConfigurationError (from current app_harness.py)
    recording_api.py     # RecordingApi, ApiCall (from current recording_api.py + api_call.py)
    config.py            # make_test_config (from current config.py)
    exceptions.py        # DrainError, DrainFailure, DrainTimeout (from current exceptions.py)
    _simulation.py       # SimulationMixin (private impl, used by AppTestHarness)
    _time_control.py     # TimeControlMixin (private impl, used by AppTestHarness)
    _sync_facade.py      # RecordingSyncFacade (private impl, used by RecordingApi)
    _factories.py        # Tier 1 factory functions (from current helpers.py + factories.py)
```

Private `_`-prefixed modules hold implementation that the public API depends on but that app authors should not import directly.

**Module layout for `tests/support/`:**

```
tests/support/
    __init__.py
    harness.py           # HassetteHarness, preserve_config, wait_for
    fixtures.py          # all pytest fixtures (build_harness, hassette_harness, etc.)
    factories.py         # Tier 2 factories (make_mock_listener, make_scheduler, etc.)
    helpers.py           # create_listener, write_app, make_task_bucket, noop, etc.
    web.py               # create_hassette_stub, web response/manifest/telemetry/job helpers
    websocket.py         # build_fake_ws, ws mocks
    config.py            # TEST_TOKEN, TEST_SOURCE_LOCATION, other test constants
    sql.py               # sqlite_conn, insert_execution_row
    server.py            # SimpleTestServer, uvicorn helpers
    reset.py             # reset_state_proxy, reset_bus, etc.
    resource_tracker.py  # ResourceTracker, pytest hooks
    state_proxy_mocks.py # configure_state_proxy_mock
    mock_hassette.py     # make_mock_hassette (if demoted), make_ws_hassette_stub
```

The question of whether `make_mock_hassette` stays public or moves internal is explicitly called out in the issue's acceptance criteria as requiring a decision. It is Tier 1 today (in `__all__`), documented in the docs site, and the second most-imported symbol (48 imports). Keeping it public is the safer default.

**Import transformation rules (for the codemod):**

| Current import path | New import path |
|---|---|
| `from hassette.test_utils import <Tier1Symbol>` | `from hassette.testing import <Tier1Symbol>` |
| `from hassette.test_utils.<tier1_module> import <Tier1Symbol>` | `from hassette.testing import <Tier1Symbol>` (or `from hassette.testing.<module>`) |
| `from hassette.test_utils import <Tier2Symbol>` | `from tests.support.<module> import <Tier2Symbol>` |
| `from hassette.test_utils.<tier2_module> import <Tier2Symbol>` | `from tests.support.<module> import <Tier2Symbol>` |

**Codemod strategy:**

A Python AST-based codemod (using `libcst` or `ast` + token preservation) is the safest approach for 444 import statements. The transform is deterministic: each symbol maps to exactly one new location. A sed/regex approach would work for most cases but risks breaking multi-line parenthesized imports. The codemod should:

1. Parse the symbol-to-new-module mapping from a JSON manifest.
2. Rewrite every `from hassette.test_utils...` import to its new path.
3. Sort imports per ruff's convention (the pre-commit hook will catch ordering issues regardless).
4. Be committed as a tool in the repo so the transform is reproducible and reviewable.

An alternative is to use ruff's import-sorting plus a two-step find-and-replace (rename the package path, then let ruff sort), followed by a verification pass.

**Pros:**
- Clean namespace: `hassette.testing` reads as a supported API surface, not repository plumbing.
- Wheel hygiene: ~5,000 lines of internal test code stop shipping to users.
- Unblocks three hard-blocked milestone issues (#1356, #1358, #1359).
- The Tier 1/Tier 2 classification already exists and is tested -- no judgment calls needed.
- `tests/support/` needs no special configuration beyond an `__init__.py`.

**Cons:**
- Enormous diff (257 files, 444 import changes, plus file moves) makes review harder.
- Concurrent work on any of the nine in-milestone issues that touch the same files will conflict.
- The `make_mock_hassette` public/internal decision needs resolution before starting.
- Documentation, CLAUDE.md, rules files, and two pre-commit tools all need coordinated updates.

**Effort estimate:** Medium-Large. The file moves and `hassette.testing` creation are straightforward. The codemod is medium effort to write and validate. The coordinated documentation and tooling updates are small individually but numerous. Total: a focused 1-2 session effort.

**Dependencies:** None new. The codemod could use `libcst` (already a dev dependency if available) or plain `ast` + string manipulation.

### Option B: `hassette.testing` + keep Tier 2 in-place as `hassette._test_internals`

An alternative that avoids the `tests/support/` discovery question entirely: rename only the public surface to `hassette.testing`, and rename the internal modules to `hassette._test_internals` (underscore-prefixed package, still shipped but signaled as private). The `pytest_plugins` registration would change from `hassette.test_utils.fixtures` to `hassette._test_internals.fixtures` -- same installed-package resolution mechanism, no rootdir dependency.

**Pros:**
- Simpler mechanically: the internal files stay under `src/hassette/`, so no pytest path-resolution change needed.
- `pytest_plugins` stays as an installed-package import path.
- Still achieves the primary goal: `hassette.testing` is the only supported public namespace.

**Cons:**
- Internal test code still ships in the wheel (~5,000 lines). This was one of the three stated motivations for the change.
- The `_` prefix is a weaker signal than physical absence from the package. Users can still `from hassette._test_internals import HassetteHarness` and will, because autocomplete shows it.
- Does not satisfy the acceptance criterion "The built wheel does not contain Hassette-only test-support modules."
- The issue body explicitly proposes `tests/support/` and explicitly rejects keeping internals in the installed package.

**Effort estimate:** Medium. Same import migration scope, but no `tests/support/` configuration work. Slightly simpler codemod (both old and new paths are installed-package imports).

## Concerns

### Technical risks

- **`pytest_plugins` resolution change.** Moving fixtures from `hassette.test_utils.fixtures` (installed-package path) to `tests.support.fixtures` (rootdir-based path) changes the underlying resolution mechanism. This works today for `tests.coverage_integrity` (already registered the same way), but the fixtures module is higher-traffic and more complex. Verify with an explicit test that `tests.support.fixtures` loads correctly in all three test runners (local `pytest`, `nox`, CI).
- **Mixed-module symbols.** `helpers.py` and `mock_hassette.py` each contain both Tier 1 and Tier 2 symbols. The migration must split these files -- Tier 1 functions move to `hassette.testing/_factories.py`, Tier 2 functions move to `tests/support/helpers.py`. The codemod manifest must map at the symbol level, not the module level.
- **`simulation.py` and `time_control.py` are private implementation of the public `AppTestHarness`.** They define mixins that `AppTestHarness` inherits from. They must stay in `src/hassette/testing/` (as `_simulation.py`, `_time_control.py`) because `AppTestHarness` imports them at class-definition time. They cannot move to `tests/support/` without creating a public-imports-internal dependency.
- **`sync_facade.py` is exposed via `RecordingApi`.** `RecordingSyncFacade` is accessible as `harness.api_recorder.sync` -- an attribute of the Tier 1 `RecordingApi`. The class itself is Tier 2 (not in `__all__`), but it is reachable from the public API. It should stay in `hassette.testing/` as a private module (`_sync_facade.py`).

### Complexity risks

- **Codemod correctness.** Multi-line parenthesized imports (`from hassette.test_utils import (\n    X,\n    Y,\n)`) where X is Tier 1 and Y is Tier 2 need to be split into two separate import statements targeting different packages. This is the hardest codemod case. Verify with a dry-run on the full test suite before applying.
- **Two "factories" modules.** After the split, `hassette.testing/_factories.py` holds Tier 1 factories and `tests/support/factories.py` holds Tier 2 factories. Both source the same conceptual registry. The `check_test_factories.py` tool must be updated to point at both locations.

### Maintenance risks

- **Documentation drift.** Seven markdown files, two tool scripts, and two CLAUDE rules files reference `hassette.test_utils` paths. These must all be updated in the same PR, and future changes to the testing API must update them coordinately. The existing `test_public_api_surface.py` test should be migrated to verify `hassette.testing.__all__` instead.
- **Downstream milestone issues.** If any of the nine non-blocked milestone issues have in-flight work on branches, those branches will need rebasing after #1333 merges. Coordinate timing to minimize conflicts.

## Resolved Questions

- [x] **`make_mock_hassette` disposition:** **Demote to internal (`tests/support`).** The primary external consumer does not use it — it was explicitly evaluated and concluded to solve a different problem. The 48 internal imports are all within hassette's own test suite. Private-to-public is easier to reverse than the opposite, so start internal and promote if a concrete app-author use case emerges (aligns with #1356's question).
- [x] **External consumer status:** An external consumer uses `AppTestHarness` (Tier 1) extensively, plus several Tier 2 helpers (`HassetteHarness`, `wait_for`, `build_harness`, `make_sensor_state_dict`, `make_state_dict`, `make_full_state_change_event`). It does not use `make_mock_hassette`. Migration of its imports is required but handled separately.
- [x] **`EventCapture` disposition:** **Keep Tier 1.** Promoted to `hassette.testing` alongside `dummy_cache`.
- [x] **Codemod tooling choice:** **`libcst`.** Handles multi-line imports natively, preserves formatting. Worth the dev dependency for a one-time migration tool.
- [x] **`dummy_cache` in Tier 1:** **Keep Tier 1.** Stays in `hassette.testing`.

## Recommendation

The proposed approach (Option A) is well-grounded. The Tier 1/Tier 2 boundary is already defined, tested, and documented -- this migration makes the boundary structural rather than conventional. The scope is large but mechanical, and a codemod reduces the risk of the 444-import migration to near-zero.

The main risk is coordination, not technical difficulty. #1333 should land before any other Testing API Redesign milestone work begins on the same files. Given that three issues are hard-blocked on it and nine more touch the same files, executing #1333 first maximizes parallel capacity for the rest of the milestone.

Option B (keeping internals in the installed package as `hassette._test_internals`) is simpler but does not satisfy the stated acceptance criteria and leaves the wheel-hygiene motivation unaddressed. It is not recommended.

### Suggested next steps

1. **Write a design doc via `/mine-define`** that specifies: the exact symbol-to-module mapping for all ~90 re-exported symbols (with `make_mock_hassette` demoted to Tier 2), the `tests/support/` module layout, and the `libcst` codemod approach.
2. **Build the codemod as a committed tool** (`tools/migrate_test_imports.py`) so the transform is reproducible, reviewable, and can be dry-run against the full test suite before applying.
3. **Sequence #1333 before #1286 and #814** (the harness and recording_api decomposition issues), as the issue body explicitly notes their file-location assumptions need revisiting after this boundary change.
4. **Coordinate with milestone contributors** to avoid in-flight work on the files #1333 will move.

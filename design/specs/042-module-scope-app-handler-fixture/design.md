# Design: Module-Scoped App Handler Test Fixture

**Date:** 2026-04-26
**Status:** approved

## Problem

The `hassette_with_app_handler` test fixture creates and tears down a full app handler harness for every test function that uses it. This includes connecting the bus, scheduler, state proxy, and bootstrapping all app instances — a process that takes 5-10x longer than the test logic itself.

The fixture cannot be upgraded to module scope because four tests in `TestApps` mutate shared registry state (stopping apps, enabling disabled apps, modifying app configs, reloading apps) without reverting those changes. When tests share a single harness instance, mutations from one test poison the state for subsequent tests, causing order-dependent failures.

This makes integration tests that exercise the app handler unnecessarily slow and creates a maintenance trap: any new test that touches the app handler inherits the per-test overhead regardless of whether it mutates state.

## Goals

- Tests using `hassette_with_app_handler` pass in any execution order, verified across multiple random seeds
- Integration suite runtime for app-handler-consuming test modules decreases measurably (before/after timing captured)
- No test depends on side-effects left by a previous test

## User Scenarios

### Developer: Integration Test Author
- **Goal:** Write and run app handler integration tests without per-test harness overhead
- **Context:** During local development, running the integration suite frequently

#### Running integration tests after changes

1. **Runs the test suite**
   - Sees: All tests pass regardless of execution order
   - Then: Suite completes faster than before due to shared harness

2. **Adds a new test that reads app state**
   - Sees: Test receives a clean, deterministic harness state identical to what a fresh fixture would provide
   - Then: No need to add cleanup logic in the new test

3. **Adds a new test that mutates app state**
   - Sees: Mutation does not affect subsequent tests — the per-test reset restores state automatically
   - Then: Author does not need to know about or manage the restore mechanism

#### Reset fails during test teardown

1. **Reset raises an exception (e.g., bootstrap_apps() fails)**
   - Sees: The current test fails with a traceback pointing at the reset function, matching the behavior of existing reset functions in the harness
   - Then: Developer diagnoses from the stack trace; no error is swallowed or masked

## Functional Requirements

1. Between each test function that uses the app handler fixture, the harness must restore registry state to the post-bootstrap baseline — running apps, manifest configuration, and failure records must match the initial state
2. The restore mechanism must shut down any app instances started during the previous test and restart any that were stopped, producing the same set of running apps as the initial bootstrap
3. The restore must use a deep copy of the original manifest configuration, not a reference — mutations to manifest objects during a test must not persist
4. The fixture must be created once per test module and shared across all tests in that module
5. The per-test cleanup must integrate with the existing `cleanup_harness` autouse fixture via the `_HARNESS_FIXTURES` registry
6. Test modules that use the fixture but do not mutate state (read-only tests) must continue to work without modification
7. The `hassette_with_app_handler_custom_config` fixture is out of scope — it uses temp paths and is already isolated by design

## Edge Cases

1. **Test that stops an app then another test expects it running** — the reset must restart the stopped app from the manifest snapshot, not from the mutated registry state
2. **Test that modifies manifest config in-place** (e.g., changing `app_config` dict values) — shallow copy is insufficient; `model_copy(deep=True)` on Pydantic models required
3. **Test that enables a disabled app** — the reset must stop the newly-started app and restore the manifest's `enabled=False` flag
4. **Bootstrap events during reset** — `bootstrap_apps()` fires `APP_LOAD_COMPLETED` bus events; these must not accumulate stale listeners from the previous test (bus reset ordering matters)
5. **Failed app instances during a test** — `clear_all()` must wipe `_failed_apps` so failure records don't leak
6. **Blocked apps** — `clear_all()` must also wipe `_blocked_apps` to prevent block reasons from persisting
7. **Reset failure during bootstrap** — if `bootstrap_apps()` raises during reset, the exception propagates (matching existing reset function behavior), failing the current test with a traceback. No error swallowing or cascade prevention — the developer diagnoses from the stack trace
8. **Reset failure during app shutdown** — if `stop_app()` raises for one app instance, the reset should still attempt to stop remaining apps before propagating the error

## Acceptance Criteria

1. All tests in `test_apps.py`, `test_app_factory_lifecycle.py`, and `test_hot_reload.py` pass with module-scoped fixture
2. All tests in `test_apps.py` pass across at least 5 different random orderings using varied random seeds
3. Integration suite runtime for test modules using this fixture decreases by at least 2x compared to function-scoped baseline
4. Full `nox -s dev` suite passes with no new failures
5. No test in the suite depends on execution order for correctness

## Dependencies and Assumptions

- `bootstrap_apps()` is safe to call on a cleared registry with restored manifests (confirmed: returns early if manifests empty, starts fresh instances otherwise)
- `AppManifest` supports `model_copy(deep=True)` as a Pydantic model
- `clear_all()` on `AppRegistry` clears `_apps`, `_failed_apps`, and `_blocked_apps` but not `_manifests`
- The existing `cleanup_harness` autouse fixture fires `harness.reset()` before each test for all fixtures in `_HARNESS_FIXTURES`
- `pytest-randomly` is available for order-independence verification
- With `pytest-xdist` (`-n 2`), each worker process gets its own module-scoped fixture instance — no cross-worker state sharing. The `--dist loadscope` strategy groups tests by module, so all tests in a module run on the same worker

## Architecture

### Reset function: `reset_app_handler()` in `src/hassette/test_utils/reset.py`

Add an async function following the existing reset pattern:

```python
async def reset_app_handler(
    app_handler: AppHandler,
    original_manifests: dict[str, AppManifest],
) -> None:
```

The function performs a full bootstrap cycle:
1. **Stop running apps** — iterate `app_handler.registry.apps` and call `app_handler.lifecycle.stop_app()` for each
2. **Clear registry** — call `app_handler.registry.clear_all()` to wipe apps, failures, and blocked records
3. **Restore manifests** — call `app_handler.registry.set_manifests()` with deep copies via `model_copy(deep=True)`
4. **Re-bootstrap** — call `await app_handler.lifecycle.bootstrap_apps()` to restart apps from the restored manifests

This mirrors the framework's own startup path, making it the most reliable restore mechanism. The trade-off is reset speed — a full stop/clear/bootstrap cycle is slower per test than a minimal diff-and-patch approach, but eliminates entire categories of missed-state bugs that a targeted restore could miss.

### Manifest snapshot in `HassetteHarness`

In `src/hassette/test_utils/harness.py`:

- Add `_original_app_manifests: dict[str, AppManifest] | None` instance attribute, initialized to `None`
- After `_start_app_handler()` completes (post-bootstrap), capture `{k: v.model_copy(deep=True) for k, v in self.app_handler.registry.manifests.items()}`
- In `reset()`, add an `app_handler` guard block that calls `reset_app_handler(self.app_handler, self._original_app_manifests)`

### Reset ordering

The reset order in `Harness.reset()` must account for `bootstrap_apps()` firing bus events:

1. **Reset app_handler** first — stops old apps, clears registry, re-bootstraps (fires `APP_LOAD_COMPLETED` events through the bus)
2. **Reset bus** second — clears any listeners added by the previous test, including any residual listeners from bootstrap events
3. **Reset scheduler** third — clears jobs (some may have been added by bootstrap)
4. **Reset state_proxy** — independent, order doesn't matter relative to the above

### conftest integration

In `tests/integration/conftest.py`:

- Add `"hassette_with_app_handler"` to `_HARNESS_FIXTURES`
- Remove the exclusion comment

### Fixture scope upgrade

In `src/hassette/test_utils/fixtures.py`:

- Change `hassette_with_app_handler` to `scope="module"`
- Remove the blocker comment (lines 106-108)

### Files affected

| File | Change |
|------|--------|
| `src/hassette/test_utils/reset.py` | Add `reset_app_handler()` |
| `src/hassette/test_utils/harness.py` | Add manifest snapshot capture + reset integration |
| `tests/integration/conftest.py` | Add fixture to `_HARNESS_FIXTURES` |
| `src/hassette/test_utils/fixtures.py` | Upgrade scope to `"module"`, remove blocker comment |

No production code changes. No new files.

## Alternatives Considered

### Minimal restore via `apply_changes()` diff

Instead of full bootstrap, compute a diff between current running apps and the desired state, then call `apply_changes()` with the appropriate `ChangeSet`. Rejected because: requires constructing a correct `ChangeSet` that accounts for all mutation types (orphans, new apps, reloads), which is fragile and duplicates logic that `bootstrap_apps()` already handles. The full cycle is simpler and more reliable.

### Per-test save/restore fixture inside `TestApps`

Add an autouse fixture in the `TestApps` class that snapshots and restores state. Rejected because: this pushes cleanup responsibility to individual test classes rather than the harness, creating a maintenance trap where new test classes must remember to add their own restore fixture. The harness-level approach is centralized and automatic.

### Keep function scope, optimize harness construction

Make the harness creation faster instead of sharing it. Rejected because: the overhead is inherent to bootstrapping real components (bus, scheduler, state proxy, app instances). The only way to meaningfully reduce it is to not do it per-test, which is exactly what module scope provides.

## Test Strategy

No new test files. Verification is through the existing integration suite:

1. **Order-independence** — run `test_apps.py` with `pytest-randomly` across 5+ random seeds
2. **Regression** — full `nox -s dev` suite must pass
3. **Performance** — capture before/after timing of `test_apps.py` module execution to confirm measurable speedup
4. **Cross-module** — verify `test_app_factory_lifecycle.py` and `test_hot_reload.py` continue to pass (they use the fixture but don't mutate state, or use `_custom_config` variant)

## Impact

- **Blast radius**: Test infrastructure only — 4 files modified, all in `test_utils/` or `tests/integration/`
- **No production code changes**
- **No API changes**
- **Risk**: If the reset function misses a state vector, tests will fail non-deterministically based on execution order. Mitigated by randomized-order verification across multiple seeds.

## Open Questions

None.

# Context: Test Infrastructure Deduplication & LLM Prevention

## Problem & Motivation
The test infrastructure has accumulated 173 local `make_*/build_*` factory functions across 387 test files, while the shared `test_utils/factories.py` holds only 3 factories. The same conceptual object (ScheduledJob, Event, CommandExecutor mock) is built 6-11 different ways across sibling files. Factory names are overloaded — `make_job` and `make_manifest` each mean different return types depending on which file you're in. This duplication is the predictable result of LLM-assisted development without structural prevention: no lint rule catches factory reinvention, and the discovery chain to TESTING.md requires two hops.

## Visual Artifacts
None.

## Key Decisions
1. New factories go in `src/hassette/test_utils/factories.py`, following the existing keyword-only style with sensible defaults. Six new factories: `make_scheduled_job`, `make_mock_executor`, `make_mock_event`, `make_recording_api`, `make_hassette_event`, `make_mock_parent`.
2. Factories returning real objects use `make_` prefix; mock-returning factories use `make_mock_` prefix. `make_recording_api` returns a real `RecordingApi` wired to mocks — `make_` prefix because the return type is the real object.
3. The linter (`tools/check_test_factories.py`) uses a flat `SHARED_FACTORIES` registry dict — name match alone triggers a violation. Exemption via `# factory-local: <reason>` annotation on the `def` line.
4. `.claude/rules/test-conventions.md` closes the two-hop discovery gap by naming canonical factories directly, with one-hop links to TESTING.md.
5. The sync `noop()` in `helpers.py` (zero callers) is replaced by the async version from `tests/unit/scheduler/conftest.py`.
6. `make_test_config` in `tests/unit/conftest.py` is renamed to `make_sync_executor_config` to resolve collision with public `test_utils.config.make_test_config`.

## Constraints & Anti-Patterns
- Do NOT restructure `harness.py` (820 lines) — separate scope.
- Do NOT split `recording_api.py` or make its CRUD methods table-driven.
- Do NOT change test directory structure or co-locate tests with source.
- Do NOT replace `hassette_instance` in `tests/integration/conftest.py` with `HassetteHarness` — separate spec.
- Do NOT remove `@pytest.mark.asyncio(loop_scope="function")` markers — only bare `@pytest.mark.asyncio` in `test_logging_service.py` are no-ops.
- New factories must use keyword-only args (`*`), every field has a default, imports shared constants from `test_utils.config` where applicable.
- Factory renames must update all import sites in the same commit — no parallel old/new paths.
- CLAUDE.md files in test directories must stay under 20 lines each.
- The linter follows pre-commit `tools/check_*.py` pattern (uses `lint_helpers.py`, `run_check()`, AST-based), NOT `check_internal_patches.py` (CI-only).
- `check_internal_patches.py` is CI-only — do not use as the wiring exemplar.

## Design Doc References
- `## Problem` — quantifies the duplication debt and explains why it accumulated
- `## Functional Requirements` — FR#1-FR#20, the complete list of changes
- `## Edge Cases` — legitimately-different local factories, name collisions, linter false positives
- `## Acceptance Criteria` — AC#1-AC#11, verifiable grep checks and test suite pass
- `## Architecture` — factory consolidation table, linter design, rule file design, test directory CLAUDE.md structure
- `## Replacement Targets` — tabular summary of what replaces what
- `## Convention Examples` — real code snippets for factory style, mock factory style, linter pattern, fixture override documentation

## Convention Examples
### Existing factory style (keyword-only, defaults, real return type)

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_listener_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    handler_method: str = "test_app.on_event",
    topic: str = "hass.event.state_changed",
    source_tier: SourceTier = "app",
) -> ListenerRegistration:
    return ListenerRegistration(
        app_key=app_key, instance_index=instance_index, ...
    )
```

### Mock factory style (no args, descriptive docstring)

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_invoke_handler_cmd(
    *,
    source_tier: SourceTier = "app",
    listener_id: int = 1,
    topic: str = "test/topic",
    listener: Any | None = None,
    event: Any | None = None,
) -> MagicMock:
    """Build a MagicMock spec'd to InvokeHandler with an invocable listener."""
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = source_tier
    ...
    return cmd
```

### Pre-commit linter pattern (AST-based, sys.exit)

**Source:** `tools/check_lazy_imports.py` (pre-commit hook exemplar)

Uses `lint_helpers.py` module for `REPO_ROOT`, `DEFAULT_SCAN_DIRS`, `iter_python_files()`, `run_check()`. AST-based detection via `ast.NodeVisitor` subclass. Exemption annotations via regex. `main()` calls `run_check()`.

### Fixture override documentation pattern

**Source:** `tests/integration/telemetry/conftest.py`

```python
@pytest.fixture
def db_hassette(premigrated_db_path, ...) -> Hassette:
    """Override of tests/integration/conftest.py::db_hassette.

    Adds web_api={"run": True} so telemetry endpoints are reachable.
    """
```

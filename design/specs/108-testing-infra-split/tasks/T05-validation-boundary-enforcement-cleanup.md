---
task_id: "T05"
title: "Validate, enforce boundary, delete old package"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#3", "FR#6", "FR#7", "AC#2", "AC#3", "AC#4", "AC#6"]
---

## Summary

Final validation and cleanup task. Updates `test_public_api_surface.py` to verify the new `hassette.testing` package, adds a `wheel_smoke` nox session to verify the wheel boundary, adds a `testing-isolation` AST rule to `check_module_boundaries.py` to enforce the one-way dependency invariant, and deletes the old `src/hassette/test_utils/` package. Runs the full test suite and lint suite to confirm everything passes.

## Target Files

- modify: `tests/unit/test_public_api_surface.py`
- modify: `noxfile.py` (add `wheel_smoke` session)
- modify: `tools/check_module_boundaries.py` (add `testing-isolation` AST rule)
- delete: `src/hassette/test_utils/__init__.py`
- delete: `src/hassette/test_utils/api_call.py`
- delete: `src/hassette/test_utils/app_harness.py`
- delete: `src/hassette/test_utils/config.py`
- delete: `src/hassette/test_utils/event_capture.py`
- delete: `src/hassette/test_utils/exceptions.py`
- delete: `src/hassette/test_utils/factories.py`
- delete: `src/hassette/test_utils/fixtures.py`
- delete: `src/hassette/test_utils/harness.py`
- delete: `src/hassette/test_utils/helpers.py`
- delete: `src/hassette/test_utils/mock_hassette.py`
- delete: `src/hassette/test_utils/recording_api.py`
- delete: `src/hassette/test_utils/reset.py`
- delete: `src/hassette/test_utils/resource_tracker.py`
- delete: `src/hassette/test_utils/simulation.py`
- delete: `src/hassette/test_utils/sql_helpers.py`
- delete: `src/hassette/test_utils/state_proxy_mocks.py`
- delete: `src/hassette/test_utils/sync_facade.py`
- delete: `src/hassette/test_utils/test_server.py`
- delete: `src/hassette/test_utils/time_control.py`
- delete: `src/hassette/test_utils/uvicorn_server.py`
- delete: `src/hassette/test_utils/web_job_helpers.py`
- delete: `src/hassette/test_utils/web_manifest_helpers.py`
- delete: `src/hassette/test_utils/web_mocks.py`
- delete: `src/hassette/test_utils/web_response_helpers.py`
- delete: `src/hassette/test_utils/web_telemetry_helpers.py`
- delete: `src/hassette/test_utils/ws_mocks.py`
- read: `design/specs/108-testing-infra-split/design.md`

## Prompt

### Step 1: Update `test_public_api_surface.py`

Rewrite `tests/unit/test_public_api_surface.py` to verify `hassette.testing` instead of `hassette.test_utils`:

1. Change the module import — after T03's codemod, this line will be `import hassette.testing as test_utils` (codemod preserved the alias). Change it to `import hassette.testing as testing`
2. Update `TIER1_SYMBOLS` set to match the design doc's 21-symbol Tier 1 set:
   - Remove: `make_mock_hassette` (demoted)
   - Add: `EventCapture`, `HassetteHarness`, `wait_for`, `build_harness`, `make_full_state_change_event` (promoted)
3. Update `test_tier1_in_all` to check `hassette.testing.__all__`
4. Rewrite `test_tier2_not_in_all` — remove assertions that `HassetteHarness` and `wait_for` are not in `__all__` (they're now Tier 1). Add `make_mock_hassette` to the "not in all" assertions.
5. Rewrite `test_tier2_importable` — this test's premise changes. It should verify that Tier 2 symbols are NOT importable from `hassette.testing` directly (e.g., `from hassette.testing import make_mock_hassette` raises `ImportError`).
6. Update `test_star_import_only_tier1` — change module reference, update tier2_samples to include `make_mock_hassette` and exclude `HassetteHarness`/`wait_for`.
7. Add a new test `test_test_utils_removed` that verifies `import hassette.test_utils` raises `ModuleNotFoundError`.

### Step 2: Add `wheel_smoke` nox session

Add a new nox session to `noxfile.py`:

```python
@nox.session(python=PYTHON_VERSIONS[0])
def wheel_smoke(session: nox.Session) -> None:
    """Build wheel and verify package boundary."""
    session.run("uv", "build", "--wheel", external=True)
    # Install in isolated env
    whl = next(Path("dist").glob("hassette-*.whl"))
    session.install(str(whl))
    # Verify Tier 1 importable
    session.run("python", "-c", "from hassette.testing import AppTestHarness")
    # Verify old package removed
    session.run(
        "python", "-c",
        "import importlib; "
        "try:\n"
        "    importlib.import_module('hassette.test_utils')\n"
        "    raise AssertionError('hassette.test_utils should not be importable')\n"
        "except ModuleNotFoundError:\n"
        "    pass",
    )
```

Adapt the pattern to match the project's existing nox session conventions (read `noxfile.py` first). The wheel smoke test must build with `uv build`, install in an isolated venv, and verify both the positive (Tier 1 importable) and negative (old package removed) cases.

### Step 3: Add `testing-isolation` AST rule

Add a new rule to `tools/check_module_boundaries.py` that AST-checks the one-way dependency invariant (AC#6). The rule must:
- Scan all `.py` files under `src/hassette/testing/`
- Flag any `import tests.support...` or `from tests.support...` statement
- Return a non-zero exit code if any are found

Read the existing rules in `check_module_boundaries.py` to follow the established pattern for rule definitions.

### Step 4: Delete old package

Delete the entire `src/hassette/test_utils/` directory. All 27 `.py` files listed in the Target Files section above. After deletion, `import hassette.test_utils` must raise `ModuleNotFoundError`.

### Step 5: Full verification

1. Run `uv run nox -s dev` — all tests must pass (AC#1, verified here as the final gate).
2. Run `prek -a` — lint + type check must pass (AC#2).
3. Run `uv run nox -s wheel_smoke` — wheel boundary verified (AC#3).
4. Run `uv run pytest tests/unit/test_public_api_surface.py -v` — __all__ verified (AC#4).
5. Run `grep -r "hassette.test_utils" src/ tests/ tools/ docs/ scripts/ codegen/ .claude/ prek.toml ruff.toml` — zero matches outside `design/` and `CHANGELOG.md` (AC#5 final check).
6. Run `grep -r "from tests.support" src/hassette/testing/` — zero matches AND the new `testing-isolation` rule in `check_module_boundaries.py` passes (AC#6).

## Focus

- Delete `src/hassette/test_utils/` AFTER updating the test file and adding the nox session — the test file's new `test_test_utils_removed` test needs the old package to be gone.
- The `wheel_smoke` nox session runs in an isolated venv — it cannot import from the repo's `tests/` directory. This is by design: it verifies the installed wheel, not the development tree.
- `check_module_boundaries.py` already has boundary rules. Read the file to understand the pattern before adding the new `testing-isolation` rule. The rule should use AST walking (not grep) to catch all import forms.
- After deletion, any remaining `from hassette.test_utils` import anywhere in the codebase will cause an `ImportError`. The codemod (T03) and string cleanup (T04) should have caught them all, but the full test suite run here is the final proof.
- `prek -a` runs ruff, pyright, and all pre-commit hooks. T04 updated `ruff.toml` paths, so the lint rules should apply to the new `hassette.testing/` module correctly.

## Verify

- [ ] FR#3: `python -c "import hassette.test_utils"` raises `ModuleNotFoundError`
- [ ] FR#6: `grep -r "from tests.support" src/hassette/testing/` returns zero matches AND `tools/check_module_boundaries.py` `testing-isolation` rule passes
- [ ] FR#7: `uv run nox -s wheel_smoke` passes (wheel contains `hassette/testing/`, not `hassette/test_utils/`)
- [ ] AC#2: `prek -a` passes with zero errors
- [ ] AC#3: `uv run nox -s wheel_smoke` exits 0
- [ ] AC#4: `uv run pytest tests/unit/test_public_api_surface.py -v` passes, confirming `hassette.testing.__all__` matches the 21-symbol Tier 1 set
- [ ] AC#6: both the grep check and the AST-based `testing-isolation` rule confirm no `tests.support` imports in `src/hassette/testing/`

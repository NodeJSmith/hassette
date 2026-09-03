---
task_id: "T03"
title: "Rewrite all imports via libcst codemod"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["AC#1"]
---

## Summary

Write and run a throwaway libcst-based codemod that rewrites every `from hassette.test_utils` import statement across the entire codebase to point at the new `hassette.testing` or `tests.support` packages. This covers 261+ test files, 14 conftest files, doc snippet files, and seed scenario scripts. The codemod reads a JSON symbol manifest mapping each symbol to its new module path. After running, update `tests/conftest.py` pytest_plugins entries. The codemod script is not committed — only the rewritten files are.

## Target Files

- modify: `pyproject.toml` (add `libcst` dev dependency)
- modify: `tests/conftest.py` (update `pytest_plugins` entries)
- modify: 261+ test files under `tests/` (import path rewrites)
- modify: 14 conftest.py files under `tests/` subdirectories (import path rewrites)
- modify: `docs/pages/testing/snippets/*.py` (35 files — import rewrites)
- modify: `docs/pages/migration/snippets/*.py` (2 files — import rewrites)
- modify: `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py` (import rewrite)
- modify: `scripts/seed_scenarios/base.py` (import rewrite)
- modify: `scripts/seed_scenarios/degraded.py` (import rewrite)
- modify: `tests/unit/test_public_api_surface.py` (will be fully updated in T05, but codemod touches its imports)
- read: `src/hassette/test_utils/__init__.py` (current symbol list for manifest generation)
- read: `design/specs/108-testing-infra-split/design.md` (module mapping table and import transformation rules)

## Prompt

### Step 1: Add libcst dev dependency

Add `libcst` to the dev dependency group in `pyproject.toml`. Run `uv sync` to install.

### Step 2: Generate the symbol manifest

Create a throwaway JSON manifest file (do NOT commit it) that maps every importable symbol to its new fully-qualified module path. Derive the manifest from the actual source files using the design doc's `## Architecture → Module mapping (authoritative)` table. The manifest shape:

```json
{
  "AppTestHarness": "hassette.testing",
  "RecordingApi": "hassette.testing",
  "HassetteHarness": "hassette.testing",
  "make_mock_hassette": "tests.support.mock_hassette",
  "create_hassette_stub": "tests.support.web_mocks",
  ...
}
```

For Tier 1 symbols, the target is `hassette.testing` (the `__init__.py` re-exports them). For Tier 2 symbols, the target is the specific `tests.support.<module>`.

For imports of the form `from hassette.test_utils.<module> import <Symbol>` where `<module>` maps to a `hassette.testing._<private>` module, the target is `hassette.testing._<private>` (not `hassette.testing`, since these symbols are not in `__all__`).

### Step 3: Write the codemod

Write a libcst codemod script (throwaway, in a temp location) that:

1. **Transforms `from hassette.test_utils import X`** — looks up X in the manifest, rewrites to `from <new_module> import X`.
2. **Transforms `from hassette.test_utils.<old_module> import X`** — maps `<old_module>` to its new location using the module mapping, rewrites accordingly.
3. **Splits mixed-tier multi-line imports** — when a single `from hassette.test_utils import (X, Y)` contains both Tier 1 and Tier 2 symbols, split into two separate import statements targeting `hassette.testing` and `tests.support.<module>` respectively.
4. **Handles `import hassette.test_utils as X`** — rewrite to `import hassette.testing as X`.

Follow the import transformation rules in the design doc's `## Architecture → Codemod strategy` section.

### Step 4: Run the codemod

Run the codemod on ALL Python files under:
- `tests/`
- `docs/pages/testing/snippets/`
- `docs/pages/migration/snippets/`
- `docs/pages/core-concepts/api/snippets/managing-helpers/`
- `scripts/seed_scenarios/`

Run as a dry-run first to review the changes. Then apply.

### Step 5: Update pytest_plugins

Edit `tests/conftest.py` to change the `pytest_plugins` list from:
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

Also update the `HassetteHarness` import earlier in conftest.py (line 32) and the comment referencing `hassette.test_utils.config` (line 120).

### Step 6: Run the test suite

Run `uv run nox -s dev` (or `uv run pytest -n 4` for faster feedback) to verify all tests pass with the new imports.

## Focus

- The codemod must handle the `self-alias` pattern used in `__init__.py` re-exports (`from .module import X as X`). These appear in the current `test_utils/__init__.py` and some test files that re-export.
- `docs/pages/testing/snippets/*.py` are real Python files included via `--8<--` directives. Pyright has `reportMissingImports: none` for these paths (see `docs/pyrightconfig.json`), so broken imports would not be caught by `prek -a`. The codemod must include these.
- Some test files import from `hassette.test_utils.<module>` directly (e.g., `from hassette.test_utils.harness import HassetteHarness`). The codemod must handle both root-level and module-level imports.
- 14 conftest.py files under `tests/` subdirectories import from `hassette.test_utils`. List them first with `grep -rl "hassette.test_utils" tests/**/conftest.py`.
- The `TYPE_CHECKING`-guarded imports in test files need the same rewriting treatment.
- After the codemod, confirm no `from hassette.test_utils` imports remain: `grep -r "from hassette.test_utils" tests/ docs/ scripts/`.

## Verify

- [ ] AC#1: `uv run nox -s dev` (or `uv run pytest -n 4`) exits with zero failures

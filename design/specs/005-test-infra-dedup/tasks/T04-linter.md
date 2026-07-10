---
task_id: "T04"
title: "Add check_test_factories.py pre-commit linter"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#18", "AC#9"]
---

## Summary
Write the `tools/check_test_factories.py` linter that prevents future factory reinvention. It scans test files for local `def make_*`/`def build_*` definitions that shadow a shared factory in the registry. Wired into `.pre-commit-config.yaml`. Depends on T01 (factories exist) and T02 (migrations done, so the linter reports zero violations on a clean run).

## Target Files
- create: `tools/check_test_factories.py`
- create: `tests/unit/tools/test_check_test_factories.py`
- modify: `.pre-commit-config.yaml`
- read: `tools/check_lazy_imports.py`
- read: `tools/lint_helpers.py`

## Prompt
Write `tools/check_test_factories.py` following the pre-commit linter pattern from `tools/check_lazy_imports.py` (NOT `check_internal_patches.py` — that's CI-only).

**Design:**

1. Define a `SHARED_FACTORIES` dict mapping factory names to import paths:
   ```python
   SHARED_FACTORIES = {
       "make_scheduled_job": "hassette.test_utils.factories",
       "make_mock_executor": "hassette.test_utils.factories",
       "make_mock_event": "hassette.test_utils.factories",
       "make_recording_api": "hassette.test_utils.factories",
       "make_hassette_event": "hassette.test_utils.factories",
       "make_mock_parent": "hassette.test_utils.factories",
       "make_invoke_handler_cmd": "hassette.test_utils.factories",
       "make_manifest": "hassette.test_utils.web_helpers",
       "noop": "hassette.test_utils.helpers",
   }
   ```

2. Use `ast.NodeVisitor` to scan for `ast.FunctionDef` (and `ast.AsyncFunctionDef`) nodes whose name matches a key in `SHARED_FACTORIES`.

3. **A name match alone triggers a violation** — this is the primary detection. An LLM creating a duplicate won't have an import to check against.

4. Support `# factory-local: <reason>` annotation on the `def` line to exempt legitimately local factories. The reason must be non-empty.

5. Violation message: `"Local '<name>()' shadows shared factory — use 'from <import_path> import <name>'"`.

6. Use `lint_helpers.py` (`REPO_ROOT`, `iter_python_files()`, `run_check()`).

7. Scan only files under `tests/` (not `src/` — the shared factories themselves are in `src/`).

**Pre-commit wiring in `.pre-commit-config.yaml`:**
```yaml
- id: check-test-factories
  name: Check test factory shadowing
  language: system
  entry: ./tools/check_test_factories.py
  files: ^tests/.*\.py$
  stages: [pre-commit, pre-push]
```

**Unit tests** at `tests/unit/tools/test_check_test_factories.py`:
- Positive case: a file with `def make_mock_event()` and no `# factory-local:` → violation reported
- Negative case: a file with `def make_special_widget()` (no shared counterpart) → clean
- Exemption case: a file with `def make_mock_event(): # factory-local: returns SimpleNamespace` → clean
- Async def case: `async def noop()` → violation reported

## Focus
- Read `tools/check_lazy_imports.py` for the exact pattern — it uses an `ast.NodeVisitor` with `visit_Import`/`visit_ImportFrom`. You'll need `visit_FunctionDef` and `visit_AsyncFunctionDef` instead.
- The exemption annotation uses a `# factory-local:` comment (not `# lazy-import:` like the lazy import checker). Check the source line via `ast.get_source_segment` or by reading the file lines.
- `lint_helpers.py` provides `run_check()` which handles the output formatting and exit code.
- After T02 is complete, the linter should report zero violations. Any remaining violations indicate a missed migration.

## Verify
- [ ] FR#18: `tools/check_test_factories.py` exists, scans test files for factory shadowing, uses AST-based detection, supports `# factory-local:` exemptions
- [ ] AC#9: `./tools/check_test_factories.py` runs successfully and reports zero violations after the factory consolidation

---
task_id: "T04"
title: "Update string references and documentation paths"
status: "planned"
depends_on: ["T03"]
implements: ["AC#5"]
---

## Summary

Grep-based pass to update all non-Python string references to `hassette.test_utils` and `hassette/test_utils` across tooling, configuration files, documentation prose, codegen templates, and Claude rules files. The codemod in T03 handled Python imports; this task handles everything else — hardcoded paths in tool scripts, regex patterns in config files, prose references in docs, and template strings in codegen. Also deletes the `make_mock_hassette` docs section and its snippet file.

## Target Files

- modify: `tools/check_test_factories.py` (37 `SHARED_FACTORIES` path references + module docstring)
- modify: `tools/check_module_boundaries.py` (13 string references)
- modify: `tools/docs/gen_ref_pages.py` (module path and nav link)
- modify: `codegen/src/hassette_codegen/sync_facade/recording.py` (embedded import in template + docstring path)
- modify: `codegen/src/hassette_codegen/sync_facade/cli.py` (default path in help text)
- modify: `codegen/src/hassette_codegen/sync_facade/ast_utils.py` (docstring path reference)
- modify: `prek.toml` (hook `files` regex)
- modify: `ruff.toml` (per-file-ignore path)
- modify: `tests/TESTING.md` (29 references)
- modify: `.claude/rules/test-conventions.md` (~20 references)
- modify: `docs/pages/testing/index.md` (prose import path references)
- modify: `docs/pages/testing/factories.md` (prose + delete make_mock_hassette section)
- modify: `docs/pages/migration/testing.md` (prose import path references)
- modify: `docs/pages/core-concepts/cache/index.md` (prose reference to dummy_cache)
- modify: `docs/document-codegen.md` (prose reference to recording_api.py path)
- modify: `docs/pages/core-concepts/api/managing-helpers.md` (if references exist — check first)
- modify: `.claude/skills/doc-accuracy-review/references/briefing-template.md` (source path mapping)
- modify: `.claude/skills/doc-coverage-review/REFERENCE.md` (module reference)
- modify: `tests/unit/tools/test_check_module_boundaries.py` (string assertions referencing `hassette.test_utils` and `test_utils-isolation` rule name)
- modify: `tests/unit/tools/test_check_test_factories.py` (string assertions referencing `hassette.test_utils` module paths)
- delete: `docs/pages/testing/snippets/factories_mock_hassette.py` (orphan after make_mock_hassette section removal)
- read: `design/specs/108-testing-infra-split/design.md` (String reference cleanup table)

## Prompt

### Systematic string reference updates

Work through the design doc's `## Architecture → String reference cleanup` table file by file. For each file, read it, find all `hassette.test_utils` or `hassette/test_utils` references, and update to the appropriate new path.

#### Tooling files

1. **`tools/check_test_factories.py`**: Update the `SHARED_FACTORIES` dict — every value is a module path like `"hassette.test_utils.factories"`. Map each to its new location:
   - Factories that stayed in `tests/support/factories.py` → `"tests.support.factories"`
   - Factories that went to `hassette.testing._factories` (Tier 1) → `"hassette.testing._factories"` or `"hassette.testing"` depending on which path the factory is importable from. Check the __all__ in `hassette.testing.__init__.py` — Tier 1 factories in __all__ map to `"hassette.testing"`.
   Also update the module docstring.

2. **`tools/check_module_boundaries.py`**: Update the 13 string references. The existing rule `name="test_utils-isolation"` must be renamed to `name="test-helpers-isolation"` (NOT `testing-isolation` — that name is reserved for the new FR#6 rule T05 will add). Update the rule's `reason=` to reference `hassette.testing` instead of `hassette.test_utils`, and update the `forbids=` and `applies=` to match the new package name. Also note: AC#6 requires adding a separate `testing-isolation` rule here — that's T05's job, not this task.

3. **`tools/docs/gen_ref_pages.py`**: Update `"hassette.test_utils"` module path to `"hassette.testing"` and the nav link format.

#### Config files

4. **`prek.toml`**: Update the `generate_recording_sync_facade` hook's `files` regex from `test_utils/recording_api\.py` to `testing/recording_api\.py`.

5. **`ruff.toml`**: Update per-file-ignore path from `"src/hassette/test_utils/*.py"` to `"src/hassette/testing/*.py"`. Also add a per-file-ignore for `"tests/support/*.py"` with the same security-related suppression rules if needed (these files contain test helpers with hardcoded values). Also check if `tests/**` needs a rule allowing imports from `hassette.testing._*` private modules.

#### Codegen files

6. **`codegen/src/hassette_codegen/sync_facade/recording.py`**: The embedded import string `from hassette.test_utils.recording_api import RecordingApi, RecordingHelperClient` becomes `from hassette.testing.recording_api import RecordingApi, RecordingHelperClient`. Update the docstring path too.

7. **`codegen/src/hassette_codegen/sync_facade/cli.py`**: Update default path from `hassette/test_utils/recording_api.py` to `hassette/testing/recording_api.py`.

8. **`codegen/src/hassette_codegen/sync_facade/ast_utils.py`**: Update docstring path reference from `src/hassette/test_utils/recording_api.py` to `src/hassette/testing/recording_api.py`.

#### Documentation prose

9. **`docs/pages/testing/index.md`**: Update import path references and `[hassette.test_utils.AppTestHarness]` cross-reference links.

10. **`docs/pages/testing/factories.md`**: Update import path references. **Delete the `## make_mock_hassette` section entirely** (demoted to internal). Also delete `docs/pages/testing/snippets/factories_mock_hassette.py` to avoid orphan-snippet CI failure from `tools/docs/check_snippet_orphans.py`.

11. **`docs/pages/migration/testing.md`**: Update all migration guide references.

12. **`docs/pages/core-concepts/cache/index.md`**: Update `hassette.test_utils` reference for `dummy_cache`.

13. **`docs/document-codegen.md`**: Update path reference to `recording_api.py`.

#### Rules and internal docs

14. **`tests/TESTING.md`**: Update all 29 references. Change `hassette.test_utils` → `hassette.testing` for Tier 1 symbols, and `hassette.test_utils.<module>` → `tests.support.<module>` for Tier 2 symbols. Update the factory registry paths, mock strategy descriptions, and import examples.

15. **`.claude/rules/test-conventions.md`**: Update ~20 references. Change factory paths, import examples, and `src/hassette/test_utils/` directory references.

#### Tool characterization tests

18. **`tests/unit/tools/test_check_module_boundaries.py`**: This file contains test functions whose fixture source-strings and expected output hard-code `hassette.test_utils`, the `test_utils-isolation` rule name, and the `"test_utils"` layer name. These are NOT Python imports — they are string data fed into `check_source()` assertions. The codemod cannot touch them. Update every `hassette.test_utils` string reference, and update the rule name from `test_utils-isolation` to `test-helpers-isolation` (matching the rename in item 2 above). Read the file first to find all occurrences.

19. **`tests/unit/tools/test_check_test_factories.py`**: Contains assertion strings like `"use 'from hassette.test_utils.factories import make_mock_event'"`. These must be updated to match the new paths that `check_test_factories.py` will emit after item 1's `SHARED_FACTORIES` update.

#### Gap-check files (not in design doc's original list)

16. **`.claude/skills/doc-accuracy-review/references/briefing-template.md`**: Update `src/hassette/test_utils/` → `src/hassette/testing/` in the source path mapping.

17. **`.claude/skills/doc-coverage-review/REFERENCE.md`**: Update `src/hassette/test_utils/` → `src/hassette/testing/` in the module reference.

### Final grep verification

After all updates, run: `grep -r "hassette.test_utils" src/ tests/ tools/ docs/ scripts/ codegen/ .claude/ prek.toml ruff.toml`

Expected: zero matches outside of `src/hassette/test_utils/` itself (which still exists until T05 deletes it), historical `design/` files (frozen), and `CHANGELOG.md` (frozen).

## Focus

- `tools/check_test_factories.py` has 37 entries in `SHARED_FACTORIES` — each one is a module path that needs updating. Read the file to understand the format before editing.
- `check_module_boundaries.py` has both a string reference in a `reason=` kwarg and path references in docstrings. Update both.
- `docs/pages/testing/factories.md` — the `make_mock_hassette` section must be entirely removed, not just updated. The design doc explicitly calls this out: "Remove the `## make_mock_hassette` section entirely."
- After deleting `factories_mock_hassette.py`, run `tools/docs/check_snippet_orphans.py` to confirm no orphan. Also check if any `--8<--` directive in `factories.md` includes it.
- `tests/TESTING.md` has a mix of `hassette.test_utils` (the importable module) and `src/hassette/test_utils/` (the directory path). Both need updating but to different targets.
- Historical `design/` files and `CHANGELOG.md` are frozen — do NOT update them.

## Verify

- [ ] AC#5: `grep -r "hassette.test_utils" src/ tests/ tools/ docs/ scripts/ codegen/ .claude/ prek.toml ruff.toml` returns zero matches (excluding `src/hassette/test_utils/` itself, `design/` history files, and `CHANGELOG.md`)

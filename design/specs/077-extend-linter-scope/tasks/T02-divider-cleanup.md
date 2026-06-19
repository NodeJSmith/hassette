---
task_id: "T02"
title: "Remove section-divider comments across non-src dirs via codemod"
status: "planned"
depends_on: []
implements: ["FR#7", "AC#6"]
---

## Summary
Remove all ~455 section-divider comments (and the 1 filler phrase) from `tests/`, `scripts/`, `tools/`, `codegen/`, and `docs/`. Because the removals are near-identical and high-volume, build a small codemod that reuses the checker's own `tokenize`-based detection so it only touches real comment tokens — never string literals — then review the diff. Bare decoration rules are deleted; wrapped dividers keep their label as a plain comment.

## Target Files
- read: `tools/check_llm_cruft.py` — reuse its `DIVIDER_RULE` / `DIVIDER_WRAPPED` regexes and `check_file` detection.
- read: `tools/lint_helpers.py` — `iter_py_files` for the file list.
- modify: `tests/**/*.py` — divider/filler comments in test files (largest share: `tests/unit/cli` ~76, `tests/unit/core` ~62, plus many others — run the checker for the live list).
- modify: `scripts/**/*.py` — ~33 dividers.
- modify: `tools/**/*.py` — ~25 dividers (e.g. `tools/docs/check_doc_voice.py`, `tools/docs/gen_ref_pages.py`).
- modify: `docs/**/*.py` — ~36 dividers in snippet/tooling files.
- modify: `codegen/**/*.py` — 0 expected (confirm).
- create (throwaway, do not commit): a one-shot codemod script in `/tmp` for the bulk removal.

## Prompt
Clean every section-divider comment and the single filler phrase in `tests/`, `scripts/`, `tools/`, `codegen/`, and `docs/`, per the design doc (`design/specs/077-extend-linter-scope/design.md`, `## Architecture` layer 5 "Dividers" and `## Functional Requirements` FR#7).

Build the lever, then run it:

1. Write a one-shot codemod (in `/tmp`, NOT committed) that, for each `.py` file under the five target dirs:
   - Tokenizes the source with the `tokenize` module (same as `check_llm_cruft.check_file`) and finds `COMMENT` tokens whose body (after stripping `#` and whitespace) matches `DIVIDER_RULE` (`^[-=#*~_]{4,}$`) or `DIVIDER_WRAPPED` (`^[-=#*~_]{3,}\s+\S.*\S\s+[-=#*~_]{3,}$`). **Operating on real comment tokens is what keeps string-literal fixtures safe** — do not regex raw lines.
   - For a **bare rule** (`# --------`): delete the entire comment. If the comment was the only thing on its line, delete the line; if it was a trailing comment on a code line, strip just the comment.
   - For a **wrapped divider** (`# ===== Fixtures =====`): replace it with a plain comment containing just the label (`# Fixtures`), preserving the original indentation.
   - Also fix the single filler-phrase hit (run `check_llm_cruft.check_file` to locate it — it reports `filler — <suggestion>`); apply the suggested plainer wording by hand if the codemod can't, since there is only one.

2. Run the codemod, then **review the full diff** for correctness — especially wrapped dividers whose label must survive, and any comment that turned into an empty/dangling line.

3. **Do not touch** the checker test fixture files' string literals: `tests/unit/tools/test_check_llm_cruft.py` (and siblings) contain divider-like strings as test *data*. Since the codemod operates on tokenized comments, these won't match — confirm the diff does not modify those fixture strings.

4. Verify zero divider/filler hits remain across the five dirs by importing `check_llm_cruft.check_file` and running it over `iter_py_files(Path("."), ["tests","scripts","tools","codegen","docs"])` (see `context.md` → "Checker verification helper"). Then run `uv run pytest tests/unit/tools/ -q` to confirm the checker tests still pass.

Note: production `SCAN_DIRS` stays `["src"]` in this task — verification is via the imported `check_file`, not the pre-push hook. Widening happens in T09.

## Focus
- `DIVIDER_RULE` and `DIVIDER_WRAPPED` are at `tools/check_llm_cruft.py:42-45`; `comment_body()` at line 63 is the body-extraction helper to mirror.
- `check_llm_cruft.check_file` returns `(lineno, message)` where the message starts with `section-divider comment` for dividers — use it both to drive the codemod and to verify zero remain.
- Reconnaissance counts (run the checker for live numbers): dividers cluster in `tests/unit/cli` (~76), `tests/unit/core` (~62), `docs/` (~36), `scripts/` (~33), `tools/` (~25), `tests/integration/test_scheduler_mode.py` (~34), `tests/unit/test_sync_executor_service.py` (~30). Filler: exactly 1.
- Docstring dividers are NOT flagged (the checker only scans comment tokens for dividers, not docstrings) — reST `---` underlines in docstrings are safe and must not be removed.
- This task and the spec-token tasks (T04–T08) edit overlapping files but run sequentially (orchestrate processes one task at a time); T04–T08 depend on this task so dividers are gone before token rewording touches the same files.
- Keep the codemod in `/tmp` so it is not itself scanned/committed.

## Verify
- [ ] FR#7: importing `check_llm_cruft.check_file` and running it over `["tests","scripts","tools","codegen","docs"]` reports zero `section-divider` hits; wrapped-divider labels survive as plain comments (spot-check 3 in the diff).
- [ ] AC#6: no section-divider comment remains in the covered scope; the single filler-phrase hit is also resolved; `uv run pytest tests/unit/tools/` passes (fixture strings untouched).

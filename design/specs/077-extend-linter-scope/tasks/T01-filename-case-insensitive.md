---
task_id: "T01"
title: "Make filename token matching case-insensitive; scope-agnostic messages"
status: "done"
depends_on: []
implements: ["FR#3", "FR#4", "AC#3", "AC#10"]
---

## Summary
Make the leaked-spec-token filename check case-insensitive so lowercase task-ID segments (`t03`) are caught, while keeping content matching case-sensitive. Add unit coverage proving both. Strip `src/`-specific wording from the three checkers' user-facing messages and module docstrings so they read correctly once scope widens later. This task does NOT change `SCAN_DIRS` — the suite stays green because the only behavioral change (case-insensitive filenames) affects no existing `src/` file.

## Target Files
- modify: `tools/check_spec_tokens.py` — add `re.IGNORECASE` to `FILENAME_TOKEN_RE`; fix the `src/` literal in `main()`'s `print`; fix the module docstring's `src/` wording.
- modify: `tools/check_llm_cruft.py` — fix the `summary="...in src/"` arg and the module docstring's `src/` wording.
- modify: `tools/check_lazy_imports.py` — fix the module docstring's `src/` wording (no output literal exists to change; its `ok=` is already `SCAN_DIRS`-dynamic and its `summary=` names no directory).
- modify: `tests/unit/tools/test_check_spec_tokens.py` — add a case-insensitive-filename positive case and a case-sensitive-content negative assertion; fix the misleading `# lowercase + single digit` comment on the existing `test_t1_helpers.py` case.

## Prompt
Implement the case-insensitivity change described in the design doc (`design/specs/077-extend-linter-scope/design.md`, `## Architecture` layer 2 and `## Functional Requirements` FR#3/FR#4).

1. In `tools/check_spec_tokens.py`, compile `FILENAME_TOKEN_RE` with `re.IGNORECASE` (only this regex — leave the content `TOKEN_RE` exactly as-is, case-sensitive, with its `(?!:)` clock-time guard). `check_filename` already splits on `[._\-]` and matches whole segments, so lowercase `t03` will now match `T\d{2,}`.

2. Fix `src/`-specific human-facing strings so they no longer name `src/` (the checkers will scan more dirs after a later task):
   - `tools/check_spec_tokens.py`: the `print(f"ERROR: {total} leaked spec-artifact token(s) found in src/:")` line in `main()` — drop the `src/` (e.g. "... token(s) found:"). Also update the module docstring lines that say tokens "should never survive into `src/`" and "scanned ... into `src/`" to phrase the rule without hard-coding `src/`.
   - `tools/check_llm_cruft.py`: change `summary="AI-writing tell(s) found in src/"` to drop `src/` (e.g. "AI-writing tell(s) found:"). Update its module docstring's `src/` reference similarly. The `ok=` arg is already `SCAN_DIRS`-dynamic — leave it.
   - `tools/check_lazy_imports.py`: it has no `src/` output literal. Only update the module docstring's `src/` wording (e.g. the opening "detect lazy imports ... in src/" line).

3. In `tests/unit/tools/test_check_spec_tokens.py`, extend `test_filename_check`'s parametrize list:
   - Add a positive case proving case-insensitivity: a lowercase 2+digit segment is now flagged, e.g. `("test_t03_x.py", ["t03"])`. (The captured token preserves the file's actual casing because `check_filename` returns the matched segment — verify the expected value matches what the code returns; adjust to `["T03"]` only if the implementation upper-cases, which it does not.)
   - Keep/confirm a case-sensitive-content guard: `check_file` on a line containing lowercase prose like "frame"/"tofu" still returns `[]` (the existing `lowercase_words_not_flagged` content case already covers this — confirm it still passes).
   - Fix the comment on the existing `("test_t1_helpers.py", [])` case: after `IGNORECASE`, that segment is unflagged because it is a *single digit* (`t1`), not because it is lowercase. Update the `# lowercase + single digit` comment to say the single-digit reason, so the comment is not misleading.

Run the checker test module and confirm all cases pass.

## Focus
- `FILENAME_TOKEN_RE` is at `tools/check_spec_tokens.py:58`; the content `TOKEN_RE` is at line 53 — do NOT touch line 53.
- The `print` to fix is around `tools/check_spec_tokens.py:114`; `check_llm_cruft`'s `summary=` is around line 111.
- `check_filename` returns the matched segment verbatim (`[seg for seg in re.split(...) if FILENAME_TOKEN_RE.match(seg)]`), so a lowercase input yields a lowercase token in the result — expect `["t03"]`, not `["T03"]`.
- The existing `test_filename_check` parametrize block spans `tests/unit/tools/test_check_spec_tokens.py:89-99` (decorator at line 89, function at 98, the `# lowercase + single digit` comment at line 95); the existing content-case `lowercase_words_not_flagged` is around line 72.
- This task deliberately leaves `SCAN_DIRS = ["src"]` in all three checkers — widening happens in T09. With scope unchanged, `test_real_src_files_pass` still scans only `src/` and stays green (no `src/` file has a lowercase task-ID filename).
- Do not edit string-literal fixtures elsewhere in the checker tests (they hold intentional divider/token text as data).

## Verify
- [ ] FR#3: `check_filename(Path("test_t03_x.py"))` returns a non-empty list (lowercase task-ID segment flagged); a unit test asserts this and passes.
- [ ] FR#4: content `TOKEN_RE` is unchanged and `check_file` on a line containing "frame"/"tofu" returns `[]` (the `lowercase_words_not_flagged` case still passes).
- [ ] AC#3: the parametrized `test_filename_check` includes both a lowercase-flagged case and the single-digit-unflagged case with a corrected comment; the full checker test module passes.
- [ ] AC#10: no `src/`-specific scope wording remains in any of the three checkers' output messages or module docstrings (grep the three files for `src/` finds only path logic like `REPO_ROOT`/`SCAN_DIRS`, not scope prose).

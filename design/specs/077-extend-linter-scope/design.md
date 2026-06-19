# Design: Extend hand-written linter scope to tests/scripts/tools/codegen/docs + CI enforcement

**Date:** 2026-06-19
**Status:** approved
**Scope-mode:** expand

## Problem

Three hand-written linters guard Python hygiene in this repo:

- `tools/check_lazy_imports.py` — bans imports inside function bodies (the house no-lazy-imports rule).
- `tools/check_spec_tokens.py` — bans leaked planning codes (`AC`/`FR`/`NFR`/`WP` + number, `T` + 2+ digits) in comments, docstrings, and filenames.
- `tools/check_llm_cruft.py` — bans AI-writing tells: section-divider comments and a fixed list of filler phrases.

All three scan only `src/` (`SCAN_DIRS = ["src"]`), and their pre-push hooks are scoped to `^src/.*\.py$`. Everything outside `src/` — `tests/`, `scripts/`, `tools/`, `codegen/`, `docs/`, `examples/` — is unguarded and has accumulated the exact debt these checkers exist to prevent. (`examples/` happens to be clean today — 0 violations across its 9 files — but it is still unguarded, so it is folded into the widened scope to keep it clean going forward.) Approximate current counts (run the checkers for live numbers; see "Counts" note in Impact):

| Scope | spec-tokens | llm-cruft | lazy-imports |
|---|---|---|---|
| tests/ + scripts/ + tools/ | ~790 | ~419 (418 dividers, 1 filler) | ~32 |
| codegen/ | ~3 | 0 | ~2 |
| docs/ | 0 | ~36 (all dividers) | 0 |

Two further gaps compound this:

1. **The filename token pattern is case-sensitive.** `FILENAME_TOKEN_RE` only matches uppercase task IDs, so lowercase filename segments like `t03` in `tests/unit/bus/test_t03_registration_errors.py` slip through. Leaked planning IDs in filenames are exactly as much noise lowercased as uppercased.
2. **CI does not enforce the checkers outside `src/`.** The CI `python` job runs `prek run --all-files --hook-stage pre-push`, which *does* invoke all three checkers — but they scan only `src/` today. Separately, the job's paths-filter (`lint.yml:29–41`) lists `src/**`, `tests/**`, and `tools/**` but omits `codegen/**`, `docs/**`, and `scripts/**` — so a PR touching only one of those three directories skips the `python` job entirely. (`tests/` and `tools/` already trigger the job; they are unguarded only because the checkers don't *scan* them yet, not because CI fails to run.)

The net effect: the rules are real for `src/` but cosmetic everywhere else, and new violations land freely in the largest part of the tree (the test suite).

## Goals

- All three checkers scan `tests/`, `scripts/`, `tools/`, `codegen/`, `docs/`, and `examples/` in addition to `src/`.
- Every existing violation in those directories is cleaned so the widened checkers exit 0.
- `FILENAME_TOKEN_RE` matches case-insensitively; the two newly-flagged test files are renamed and all references updated.
- The widened checkers are enforced in CI for changes to any covered directory, including codegen-only and docs-only PRs.
- A green pre-push run and a green CI `python` job over the widened scope.

## Non-Goals

- **Frontend coverage.** `frontend/src` (`.ts`/`.tsx`/`.css`, ~261 files, ~94 dividers + ~7 spec-token-looking refs) carries the same debt, but these checkers parse with Python `tokenize`/`ast` and cannot read TS/CSS. Covering the frontend needs separate TS-aware tooling (ESLint rule or a Node checker) and is tracked in **#1086**.
- **Module-boundary / import-cycle work (#1079).** Unrelated architectural refactoring; not touched here.
- **Making the content `TOKEN_RE` case-insensitive.** Content matching stays case-sensitive by design — case-insensitivity would flag prose words like "tofu" or "frame" (documented in `check_spec_tokens.py`). Only the *filename* pattern changes, because filename segments contain no prose.
- **Renaming files beyond the two flagged by the case-insensitive filename pattern.** No broad test-file renaming campaign.

## User Scenarios

### Maintainer: repository contributor
- **Goal:** push a change without leaking planning artifacts, AI-writing tells, or lazy imports anywhere in the tree.
- **Context:** working in any Python directory — most often `tests/`.

#### Pre-push catches a violation outside src/
1. **Contributor edits a test and adds `# --- setup ---` divider plus a docstring "verifies AC#3".**
   - Sees: nothing yet — the edit looks normal.
   - Decides: to push.
   - Then: `git push` triggers the pre-push hooks.
2. **Pre-push runs the widened checkers.**
   - Sees: `check-llm-cruft` and `check-spec-tokens` fail, naming the file, line, and the offending divider / token.
   - Decides: remove the divider, reword the docstring to describe the behavior.
   - Then: re-push succeeds.

### Maintainer: reviewer on a codegen-only or docs-only PR
- **Goal:** trust that CI enforces the same hygiene rules regardless of which directory the PR touches.
- **Context:** reviewing a PR that changes only `codegen/` or only `docs/`.

#### CI runs the checkers on a narrow PR
1. **A PR changes only files under `codegen/`.**
   - Sees: the CI `python` job runs (paths-filter now includes `codegen/**`).
   - Decides: nothing — automated.
   - Then: if the codegen change introduced a leaked token or lazy import, the job fails; otherwise it passes.

## Functional Requirements

- **FR#1** Each checker (`check_lazy_imports`, `check_spec_tokens`, `check_llm_cruft`) scans `src/`, `tests/`, `scripts/`, `tools/`, `codegen/`, `docs/`, and `examples/`.
- **FR#2** With the widened scope, each checker exits 0 (no violations) against the cleaned tree.
- **FR#3** `FILENAME_TOKEN_RE` matches leaked task/spec codes case-insensitively (e.g. `t03`, `ac1`, `wp2` as whole separated filename segments).
- **FR#4** Content token detection (`TOKEN_RE` in `check_spec_tokens`) remains case-sensitive — lowercase prose words are not flagged.
- **FR#5** The two test files whose names contain lowercase task-ID segments are renamed to names with no leaked code, and every reference to them (test IDs, imports, config) is updated.
- **FR#6** Lazy imports outside `src/` are resolved per-site: hoisted to module top where that is behavior-preserving, or annotated `# lazy-import: <reason>` where the deferred import is deliberate (patching, import-timing tests, circular-avoidance in standalone scripts).
- **FR#7** Section-divider comments in the widened scope are removed; any label carried by a wrapped divider (`# --- Helpers ---`) is preserved as a plain comment (`# Helpers`).
- **FR#8** Leaked spec tokens in comments and docstrings in the widened scope are removed by rewording the surrounding text to describe the behavior, not the planning ID — the sentence must still read correctly.
- **FR#9** The pre-push hooks for all three checkers trigger on changes to any covered directory, not just `src/`.
- **FR#10** The CI `python` job is triggered for changes under `codegen/`, `docs/`, and `scripts/`, so PRs touching only those directories run the checkers. (`tests/` and `tools/` already trigger it.)
- **FR#11** User-facing `src/`-hardcoded strings reflect the widened scope: the `ERROR: ... in src/` summary in `check_spec_tokens.main`, the `summary="AI-writing tell(s) found in src/"` in `check_llm_cruft`, and the module docstrings that state the checker guards `src/`. (`check_lazy_imports` has no `src/` output literal — its `ok=` is already `SCAN_DIRS`-dynamic and its `summary=` names no directory — so only its `SCAN_DIRS` and docstring change.)
- **FR#12** The content `TOKEN_RE` catches two planning-code forms its original pattern missed, while still skipping real clock times: a planning-ID followed by a colon and non-digit (`T05: Saturation` — but not `T05:30`), and a sub-criterion letter suffix (`AC#6a`, `FR#3b`). (Added after review found these leak through the `(?!:)` clock-guard and the `\b...\d+\b` word-boundary.)

## Edge Cases

- **Wrapped divider with a meaningful label** (`# ====== Fixtures ======`): keep `# Fixtures`, drop the rule. A bare rule (`# --------`) is deleted entirely.
- **Spec token that is part of real prose, not a planning reference** — e.g. a docstring legitimately discussing an entity named with a `T##` pattern. Reword to avoid the literal token; the checker has no escape hatch by design. (None expected outside test-mapping docstrings, but reword rather than suppress if encountered.)
- **Lazy import that is the subject of the test** — `tests/unit/test_forgotten_await_completeness.py` and similar import *inside* functions deliberately to exercise import behavior. These get `# lazy-import: <reason>`, not hoisting.
- **Lazy import in a standalone script** (`scripts/export_schemas.py`, `tools/check_schemas_fresh.py`) used to break a heavy/circular import at call time — annotate with the reason if hoisting would change behavior; otherwise hoist.
- **Renamed test file referenced by name elsewhere** — pytest collects by path, but a rename still needs a check for hard references (imports of the module, `-k`/nodeid references in CI config, docs). Resolve all before finalizing.
- **A file under a covered dir that `ast.parse` cannot parse** — none currently (parse_fail=0 across all dirs in reconnaissance); no special handling needed.
- **Docstring dividers are reST, not cruft** — `check_llm_cruft` already only flags dividers in *comments*, not docstrings. Widening scope does not change this; docs snippet docstrings are safe.

## Acceptance Criteria

- **AC#1** Running each of the three checkers from the repo root exits 0. (FR#1, FR#2)
- **AC#2** `SCAN_DIRS` in all three checkers equals `["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]`, and `iter_paths()` resolves files under each. (FR#1)
- **AC#3** A file named with a lowercase segment like `test_t03_foo.py` is flagged by `check_filename`; a content line containing the lowercase word "frame" is *not* flagged by `check_file`. (FR#3, FR#4)
- **AC#4** Neither `tests/unit/bus/test_t03_registration_errors.py` nor `test_t04_once_listener_tracking.py` exists; their replacements exist with descriptive names; `uv run pytest` collects and passes the renamed files. (FR#5)
- **AC#5** No un-annotated lazy import remains in the covered scope; every remaining in-function import carries a non-empty `# lazy-import:` reason. (FR#6)
- **AC#6** No section-divider comment remains in the covered scope; spot-checked wrapped-divider labels survive as plain comments. (FR#7)
- **AC#7** No leaked spec token remains in comments/docstrings in the covered scope; spot-checked reworded docstrings read as behavior descriptions. (FR#8)
- **AC#8** Pushing a change that touches only a `tests/` file triggers all three pre-push checkers locally. (FR#9)
- **AC#9** The CI `python` paths-filter includes `codegen/**`, `docs/**`, and `scripts/**`. (FR#10)
- **AC#10** No `src/`-specific scope wording remains in the three checkers' `OK:`/`ERROR:` output or module docstrings. (FR#11)
- **AC#11** A full `prek run --all-files --hook-stage pre-push` (eslint/tsc/prettier skipped) passes. (FR#2, FR#9)
- **AC#12** A unit test asserts `check_file` flags `T05: foo` and `AC#6a` (in a comment/docstring) and does NOT flag a real clock time `T05:30:00`; the tightened `TOKEN_RE` reports zero hits across the full widened scope after cleanup. (FR#12)

## Key Constraints

- **No escape hatch for spec-tokens or cruft.** Both checkers are designed with no suppression mechanism — a match is always cleaned, never annotated. Do not add exemption comments or loosen the regexes to make violations pass; reword the text. The only annotation that exists in this system is `# lazy-import:` for `check_lazy_imports`.
- **Tighten, don't weaken, the content `TOKEN_RE`.** Keep it case-sensitive. The clock-time guard tightens from `(?!:)` to `(?!:\d)` so planning-ID-colon forms (`T05: foo`) are caught while real times (`T05:30`) are still skipped; the criterion alternation gains an optional trailing letter (`\d+[a-z]?`) so sub-criteria (`AC#6a`) are caught. `FILENAME_TOKEN_RE` becomes case-insensitive (T01). No suppression is added — the checker still has no escape hatch.
- **Behavior-preserving lazy-import fixes only.** Hoisting must not change runtime behavior. If an import is lazy to break a cycle or control timing, annotate — do not hoist and hope.
- **Reworded docstrings must stay accurate.** When removing a planning token from a test docstring, the replacement must describe what the test actually verifies — do not invent behavior to fill the sentence.

## Dependencies and Assumptions

- Assumes `prek`/pre-commit is the hook runner (confirmed: `.pre-commit-config.yaml`, CI uses `prek run`).
- Assumes the CI `python` job's `prek run --all-files --hook-stage pre-push` step is the enforcement path (confirmed: `lint.yml:85-88`).
- Assumes `iter_py_files` (in `tools/lint_helpers.py`) is the shared file-discovery helper for all three checkers (confirmed).
- No external services, data, or teams involved — internal tooling only.

## Architecture

The change has four mechanical layers and one judgment-heavy cleanup layer.

**1. Widen scan scope (checkers).** Each checker declares `SCAN_DIRS: list[str] = ["src"]` and builds paths via `iter_paths() -> iter_py_files(REPO_ROOT, SCAN_DIRS)`. Change the constant in all three to the widened list. No logic change — `iter_py_files` already `rglob`s each dir. Fix the `src/`-hardcoded human-facing strings (use `', '.join(SCAN_DIRS)` where a literal `src/` appears, matching the existing `ok=` pattern). Where each `src/` literal lives: `check_spec_tokens.py` — the `print(f"ERROR: ... in src/:")` in `main()` plus the module docstring (lines ~7–8, "should never survive into `src/`"); `check_llm_cruft.py` — the `summary="...in src/"` arg plus its module docstring; `check_lazy_imports.py` — **no output literal** (its `ok=` is already dynamic, its `summary=` names no dir), only the module docstring ("...in src/.").

**2. Filename case-insensitivity.** In `check_spec_tokens.py`, compile `FILENAME_TOKEN_RE` with `re.IGNORECASE`. This is a one-flag change; `check_filename` already splits on `[._\-]` and matches whole segments, so lowercase `t03` will match `T\d{2,}` case-insensitively. `TOKEN_RE` (content) is untouched.

**3. Hook + CI triggers.** In `.pre-commit-config.yaml`, widen each of the three hooks' `files:` regex from `^src/.*\.py$` to `^(src|tests|scripts|tools|codegen|docs|examples)/.*\.py$` (the hooks set `pass_filenames: false`, so `files:` only gates *whether* the hook runs; the checker scans its full `SCAN_DIRS` regardless). In `.github/workflows/lint.yml`, add `codegen/**`, `docs/**`, and `scripts/**` to the `python` paths-filter (lines 29–41) — `tests/**`, `tools/**`, and `examples/**` are already listed there, so they need no change. No new CI job — the existing `prek run --all-files --hook-stage pre-push` step already invokes all three checkers; widening `SCAN_DIRS` makes it cover the new dirs.

**4. File renames.** `git mv` the two `test_t0X_*.py` files to descriptive names that drop the task ID (e.g. `test_registration_errors.py`, `test_once_listener_tracking.py` — verify no name collision in the same dir first). Grep the repo for the old module names and update any references.

**5. Violation cleanup (the bulk).** Order: cheapest-to-verify first.
   - **Dividers (~454):** mechanical. A scripted lever can find them (reuse `check_llm_cruft.check_file` filtered to `section-divider`), but removal needs the keep-the-label rule, so apply per-hit with Edit. Mostly in `tests/` and `docs/`.
   - **Lazy imports (~34):** per-site, clustered (`test_sync_executor_service.py` 11, `test_scheduler_coroutine_conversion.py` 5, build scripts 3 each). Read each site, decide hoist vs annotate per FR#6.
   - **Spec tokens (~793):** the manual majority (AC ~410, FR ~316, T ~35, WP ~29), almost all in test docstrings mapping tests to acceptance criteria. Reword each to describe the verified behavior. A codemod can *locate* every hit (reuse `check_spec_tokens.check_file`) but cannot reword — this is human/agent work, sliceable per-file.

**Verification lever.** The three checkers ARE the success oracle — run them after each cleanup slice for a live, exact count. This is the deterministic re-runnable check; no separate harness needed.

## Replacement Targets

No existing code is being replaced. The checkers' logic is reused as-is; only `SCAN_DIRS`, one regex flag, output strings, hook patterns, the CI paths-filter, and the two filenames change. The violation cleanup edits content, not structure.

## Convention Examples

### Checker scope + path discovery pattern

**Source:** `tools/check_spec_tokens.py`

```python
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned, relative to the repo root.
SCAN_DIRS: list[str] = ["src"]


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output."""
    return iter_py_files(REPO_ROOT, SCAN_DIRS)
```

All three checkers share this exact shape — widening scope is changing the one constant and letting `iter_py_files` do the rest.

### Output string already parameterized on SCAN_DIRS

**Source:** `tools/check_llm_cruft.py`

```python
return run_check(
    iter_paths(),
    REPO_ROOT,
    check_file,
    summary="AI-writing tell(s) found in src/",     # <- hard-codes src/
    ok=f"no AI-writing tells found under {', '.join(SCAN_DIRS)}/.",  # <- already dynamic
)
```

The `ok=` line is the pattern to copy; `summary=` and the `print(... "in src/")` lines in `check_spec_tokens.main` are the literals to fix.

### Lazy-import annotation (the only escape hatch)

**Source:** `tools/check_lazy_imports.py` docstring

```python
# Canonical annotation form:
# lazy-import: break circular import with <module>
```

Deliberate lazy imports get this; everything else hoists. The reason after the colon is required.

### Whole-segment filename matching

**Source:** `tools/check_spec_tokens.py`

```python
# Filenames have no clock times and use '.', '_', '-' as separators ...
FILENAME_TOKEN_RE = re.compile(r"^(?:(?:AC|FR|NFR|WP)#?\d+|T\d{2,})$")
```

Add `re.IGNORECASE` here only. The `^...$` whole-segment anchoring already prevents `BAT05`-style false positives, so case-insensitivity does not widen the match beyond intent.

## Alternatives Considered

- **Relax `check_lazy_imports` for `tests/` entirely** (rejected): would leave the test suite free to accumulate lazy imports, re-opening the gap this issue closes. Case-by-case (hoist clean / annotate deliberate) keeps the rule honest while respecting the genuine patching cases.
- **Make content `TOKEN_RE` case-insensitive too** (rejected): the checker's own docstring documents why — lowercase prose words ("tofu", "frame") would match. Filenames have no prose, so only the filename pattern is safe to lowercase.
- **Add a dedicated CI job for the three checkers** (rejected): redundant. CI already runs them via `prek run --all-files --hook-stage pre-push`; the only real gap is the paths-filter omitting `codegen/`/`docs/`. Adding a job would duplicate enforcement and drift from the pre-push source of truth.
- **Auto-rewrite spec tokens with a codemod** (rejected for the reword step): deleting a token leaves a broken sentence; a codemod cannot reword accurately. Codemods are used only to *locate* hits; rewording is manual.
- **Do nothing** (rejected): the largest part of the tree stays unguarded and the debt compounds with every new test file.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/bus/test_t03_registration_errors.py` and `test_t04_once_listener_tracking.py` — renamed (FR#5). Content unchanged except any internal docstring spec-token cleanup; must still collect and pass under the new names.
- The checkers have their own pytest coverage (the `tools/` test modules run on the test path per `lint_helpers.py` docstring). If tests assert the `src/`-specific output strings or `SCAN_DIRS == ["src"]`, update them to the widened expectations. Locate via grep for `SCAN_DIRS`, `check_filename`, and the output literals in the test suite.

### New Test Coverage
- **FR#3/FR#4 (case-insensitive filename, case-sensitive content):** a unit test asserting `check_filename(Path("test_t03_x.py"))` returns a hit and `check_file` on a line containing "frame"/"tofu" returns none. (AC#3)
- **FR#2 (clean pass):** the existing checker-invocation tests, re-run over the widened scope, are the oracle. No new harness — the checkers are self-verifying. (AC#1, AC#11)
- New coverage maps to the checker test modules already in `tools/` / the test suite; add to those rather than creating a parallel structure.

### Tests to Remove
No tests to remove.

## Documentation Updates

- **CLAUDE.md** — the memory/project notes describe these as `src/`-scoped pre-push linters ("Hand-written linters ... tools/check_*.py pre-push hooks"). Update any in-repo doc or rule text that states the scope is `src/` only. Grep `CONTRIBUTING.md`, `.claude/`, and `design/` for scope claims about these checkers.
- **Hook `name:` fields** in `.pre-commit-config.yaml` (e.g. "Ban lazy imports in **src**") — reword to reflect the widened scope (these are user-facing during pre-push).
- No docs-site (`docs/pages/`) changes — the checkers are internal tooling with no user-facing docs page. (Note: `docs/` snippet *files* are cleaned as scan targets, but no prose page documents the linters.)
- No CHANGELOG edit (release-please; use `chore:`/`ci:` commit types so this internal-tooling work stays out of the changelog).

## Impact

### Changed Files

<!-- Gap check 2026-06-19: 1 gap included — tests/unit/bus/conftest.py:50 (comment referencing test_t04_once_listener_tracking.py) → T04 part A step 3. Also confirmed: checker test files (tests/unit/tools/test_check_*.py) hold divider/token-like strings as string-literal fixtures that must NOT be cleaned (checkers scan only real comments/docstrings) → noted in context.md Constraints + T02/T05/T06 Focus. -->

Cross-cutting / higher-risk first:

- **modify** `tools/check_spec_tokens.py` — widen `SCAN_DIRS`; add `re.IGNORECASE` to `FILENAME_TOKEN_RE`; fix the `src/` literal in `main()`'s `print` and the module docstring.
- **modify** `tools/check_llm_cruft.py` — widen `SCAN_DIRS`; fix the `summary=` `src/` literal and the module docstring.
- **modify** `tools/check_lazy_imports.py` — widen `SCAN_DIRS`; fix the module docstring's `src/` wording (no output literal to change).
- **modify** `.pre-commit-config.yaml` — widen `files:` regex on the three hooks; reword their `name:` fields.
- **modify** `.github/workflows/lint.yml` — add `codegen/**`, `docs/**`, and `scripts/**` to the `python` paths-filter (`tests/**`, `tools/**` already present).
- **rename** `tests/unit/bus/test_t03_registration_errors.py` → descriptive name (FR#5).
- **rename** `tests/unit/bus/test_t04_once_listener_tracking.py` → descriptive name (FR#5).
- **modify** checker test modules (paths TBD via grep) — update scope/output expectations; add the case-sensitivity unit test.
- **modify** ~100+ files under `tests/`, `scripts/`, `tools/`, `codegen/`, `docs/` — violation cleanup (dividers, lazy imports, spec tokens). Sliced per-directory in the plan.
- **modify** `CLAUDE.md` / rule text — scope wording.

**Counts:** the per-category numbers in this doc are framing, not instructions. Implementers run each checker for the live, exact set of violating files and lines before and after each slice.

### Behavioral Invariants
- `src/` enforcement is unchanged — widening `SCAN_DIRS` only adds directories; the `src/` scan and all existing `src/`-passing behavior are preserved.
- The content `TOKEN_RE` match set is unchanged (still case-sensitive, still clock-time-guarded).
- `check_llm_cruft` still ignores dividers inside docstrings (reST), not just comments.
- The renamed test files' assertions and behavior are unchanged — rename only.
- `uv run pytest` collects and passes exactly as before, modulo the two renamed paths.

### Blast Radius
- Touches the largest directory in the repo (`tests/`) broadly but shallowly (comment/docstring/import edits, no logic changes). Risk concentrates in: (a) lazy-import hoists that could change import timing — mitigated by the annotate-when-deliberate rule; (b) the two renames — mitigated by a reference grep; (c) any over-aggressive divider removal that drops a meaningful label — mitigated by the keep-the-label rule and per-hit edits.
- Contributors will see the widened checkers fire on pushes touching the new dirs — intended.

## Open Questions

None.

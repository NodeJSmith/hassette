# Context: Extend hand-written linter scope to tests/scripts/tools/codegen/docs

## Problem & Motivation

Three hand-written Python linters — `tools/check_lazy_imports.py`, `tools/check_spec_tokens.py`, `tools/check_llm_cruft.py` — enforce hygiene rules (no lazy imports, no leaked planning codes, no AI-writing tells) but scan only `src/`. Everything outside `src/` (`tests/`, `scripts/`, `tools/`, `codegen/`, `docs/`, `examples/`) is unguarded and has accumulated ~1,282 violations: ~793 leaked spec tokens (mostly `AC#`/`FR#` mapping codes in test docstrings), ~455 section-divider comments, and ~34 lazy imports. (`examples/` is already clean — 0 violations — but unguarded, so it joins the widened scope; no cleanup task needed for it.) The filename token pattern is also case-sensitive, so lowercase task-ID filename segments (`t03`) slip through. And the CI `python` paths-filter omits `codegen/`, `docs/`, and `scripts/`, so PRs touching only those dirs bypass the checkers entirely. The rules are real for `src/` but cosmetic everywhere else, and new violations land freely in the largest part of the tree (the test suite).

## Visual Artifacts

None.

## Key Decisions

1. **Clean first, widen scope last.** Each cleanup task verifies against its target files by calling the checker's own `check_file` over that scope (the functions are importable from `tools/`). Production `SCAN_DIRS` stays `["src"]` until the final flip task, so every intermediate commit stays green. The final task widens `SCAN_DIRS` and is the GREEN checkpoint — all three checkers must exit 0 over the full widened scope.
2. **Only the filename pattern goes case-insensitive.** `FILENAME_TOKEN_RE` gets `re.IGNORECASE`. The content `TOKEN_RE` stays case-sensitive on purpose — case-insensitivity would flag prose words like "tofu"/"frame" (documented in `check_spec_tokens.py`). Filename segments have no prose, so lowercasing them is safe.
3. **Lazy imports resolved case-by-case.** Hoist to module top where behavior-preserving; annotate `# lazy-import: <reason>` where the deferred import is deliberate (patching, import-timing tests like `test_forgotten_await_completeness.py`, circular-avoidance in standalone scripts). No blanket relaxation for tests.
4. **Dividers via a codemod lever.** ~455 near-identical mechanical removals — build a small script (on `tokenize`, mirroring `check_llm_cruft`'s detection) rather than hand-editing each. Bare rules (`# -----`) delete the whole comment line; wrapped dividers (`# === Setup ===`) keep the label as a plain comment (`# Setup`).
5. **No new CI job.** The CI `python` job already runs `prek run --all-files --hook-stage pre-push`, which invokes all three checkers. Widening `SCAN_DIRS` makes that step cover the new dirs automatically; the only `lint.yml` edit is adding `codegen/**`, `docs/**`, `scripts/**` to the `python` paths-filter.
6. **Frontend is out of scope** — tracked separately in #1086 (these Python checkers cannot parse `.ts`/`.tsx`/`.css`).

## Constraints & Anti-Patterns

- **Never "clean" string-literal fixtures.** The checker test files (`tests/unit/tools/test_check_spec_tokens.py`, `test_check_llm_cruft.py`, `test_check_lazy_imports.py`) deliberately contain token-like and divider-like text *as string literals in test data* (e.g. `"# the BAT05 register"`, `"# generic over T1 and T2"`). The checkers only scan real comment tokens and docstrings, so these are not violations. Do not edit them.
- **No escape hatch for spec-tokens or cruft.** These checkers have no suppression mechanism by design — a match is always cleaned by rewording/removing, never annotated. The only annotation in this system is `# lazy-import: <reason>` for `check_lazy_imports`.
- **Do not weaken the content `TOKEN_RE`.** Keep it case-sensitive and keep the `T\d{2,}(?!:)` clock-time guard. Only `FILENAME_TOKEN_RE` becomes case-insensitive.
- **Behavior-preserving lazy-import fixes only.** If hoisting an import would change runtime behavior (timing, patch targets, cycle-breaking), annotate instead of hoisting.
- **Reworded docstrings must stay accurate.** When removing a planning token from a test docstring, describe what the test actually verifies — do not invent behavior to fill the sentence.
- **Do not implement non-goals:** no frontend coverage, no module-boundary/#1079 work, no broad test-file renaming beyond the two flagged by the case-insensitive filename pattern.

## Design Doc References

- `## Problem` — the unguarded-directories gap, the case-sensitivity gap, the CI paths-filter gap.
- `## Functional Requirements` — FR#1–11; `## Acceptance Criteria` — AC#1–11.
- `## Architecture` — the five change layers (widen scope, filename flag, hook+CI triggers, renames, cleanup) with exact literal locations.
- `## Edge Cases` — wrapped-divider labels, lazy-import-as-test-subject, renamed-file references, docstring reST dividers.
- `## Convention Examples` — the checker scope pattern, the already-dynamic `ok=` string, the lazy-import annotation form, the whole-segment filename regex.
- `## Impact → Changed Files` / `Behavioral Invariants` / `Blast Radius` — risk concentration and what must not change.

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
    summary="AI-writing tell(s) found in src/",          # <- hard-codes src/, fix this
    ok=f"no AI-writing tells found under {', '.join(SCAN_DIRS)}/.",  # <- already dynamic, copy this pattern
)
```

### Lazy-import annotation (the only escape hatch)

**Source:** `tools/check_lazy_imports.py` docstring

```
# Canonical annotation form: # lazy-import: break circular import with <module>
```

Deliberate lazy imports get this; everything else hoists. The reason after the colon is required (an empty annotation does not exempt).

### Whole-segment filename matching

**Source:** `tools/check_spec_tokens.py`

```python
FILENAME_TOKEN_RE = re.compile(r"^(?:(?:AC|FR|NFR|WP)#?\d+|T\d{2,})$")
```

Add `re.IGNORECASE` here only. The `^...$` whole-segment anchoring already prevents `BAT05`-style false positives, so case-insensitivity does not widen the match beyond intent.

### Checker verification helper (how cleanup tasks confirm zero violations)

The checker functions are importable (`tools/` is on the test path). A cleanup task verifies its scope without touching production `SCAN_DIRS`:

```python
import sys; sys.path.insert(0, "tools")
from pathlib import Path
from lint_helpers import iter_py_files
from check_spec_tokens import check_file       # or check_llm_cruft / check_lazy_imports
bad = {p: check_file(p) for p in iter_py_files(Path("."), ["tests/unit/bus"]) if check_file(p)}
assert not bad, bad
```

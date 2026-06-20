---
task_id: "T04"
title: "Update boundary docstring, record DAG for 633, full verification"
status: "planned"
depends_on: ["T03"]
implements: ["FR#8", "AC#1", "AC#2", "AC#4", "AC#7"]
---

## Summary
Finalize the refactor: update the `check_module_boundaries.py` module docstring to reflect that `api→core`, `web→core`, and `utils→events` are now enforced (the rest still pending), record the revised L0–L9 layer map for issue #633, and run the full verification pass. Because `core/` is touched, this includes the system and e2e nox sessions, not just unit/integration. Confirm the `# lazy-import:` annotation count is unchanged (this PR removes none) and that no new lazy imports were introduced. Runs after all structural moves are in.

## Target Files
- modify: `tools/check_module_boundaries.py` (module docstring, lines ~13-19 — the note that the DAG "is NOT enforced here")
- create: `design/specs/078-break-import-cycles-clean-wins/issue-633-layer-map.md` (the revised L0–L9 DAG, drafted for posting as a #633 comment)
- read: `design/specs/078-break-import-cycles-clean-wins/design.md` (Architecture → target layer DAG; AC list)
- read: `tools/check_lazy_imports.py`
- read: `design/specs/078-break-import-cycles-clean-wins/tasks/context.md`

## Prompt
Read `context.md` and the design doc's `## Architecture` → "The target layer DAG (revised from #633)".

1. **Update the boundary-checker docstring.** In `tools/check_module_boundaries.py`, revise the module docstring (currently it says the full DAG and cycle-freedom "are NOT enforced here ... tracked in #1079"). Update it to state that three boundaries are now enforced — `api → core`, `web → core`, `utils → events` — while `bus → core`, `scheduler → core`, `state_manager → core` and full cycle detection remain pending (deferred ADR / #633). Keep it factual and brief; do not overstate coverage.
2. **Record the revised layer map for #633.** Write `design/specs/078-break-import-cycles-clean-wins/issue-633-layer-map.md` containing the L0–L9 DAG from the design doc's Architecture section, plus the two corrections this work fed back: `resources` sits at L4 BELOW the api/bus/scheduler service group (the code demands it — they all import `resources`), and `schemas` is added at L3 (pure-data leaf importing only `types`/`const`/`utils`). This file is the draft comment body for issue #633.
   - **Do NOT post to GitHub automatically.** Posting a public issue comment is an outward-facing action — surface the drafted file to the user and let them post it (e.g. via `gh-issue` or the web UI). State this explicitly in your completion summary.
3. **Confirm the lazy-import invariant (FR#8 / AC#4).** Run `grep -rc "lazy-import:" src/hassette` style count — it must equal the pre-PR count of 11 (this PR removes none and adds none). Run `uv run python tools/check_lazy_imports.py` (or the prek hook) and confirm it passes. If the count dropped or rose, something went wrong in T01–T03 — investigate before claiming done.
4. **Full verification pass (AC#1, AC#2):**
   - `uv run pyright` → zero errors.
   - `uv run python tools/check_module_boundaries.py` → exits zero (all four RULES satisfied).
   - `uv run nox -s tests` → unit + integration green.
   - `uv run nox -s system` → green (required: `core/` was touched).
   - `uv run nox -s e2e` → green (required: `core/` was touched; Playwright/Chromium must be installed).
   - Capture each command's output to a tmp file (`get-tmp-filename`) so failures can be inspected without re-running.
   - **Never run `pytest -n auto`** — use the nox sessions as written.

## Focus
- The system and e2e suites run with CI's `filterwarnings` config; a warning that unit tests tolerate can fail here. Read captured output on any failure rather than re-running blindly.
- The boundary docstring is the only documentation artifact that must change in-repo (no `docs/pages/` impact — internal plumbing). Do not edit `CHANGELOG.md` (release-please owns it).
- The `issue-633-layer-map.md` artifact lives under the spec dir; it is a draft, not a committed source change to the checker.
- If `nox -s e2e` cannot run (Playwright not installed in this environment), report it as an explicit observability gap rather than silently skipping — name what could not be verified.

## Verify
- [ ] FR#8: `uv run python tools/check_lazy_imports.py` passes; the `# lazy-import:` annotation count in `src/hassette` is unchanged at 11 (no new lazy imports introduced by T01–T03).
- [ ] AC#1: `uv run pyright` reports zero errors across the full tree.
- [ ] AC#2: `uv run nox -s tests`, `uv run nox -s system`, and `uv run nox -s e2e` all pass (or any unrunnable suite is named as an explicit observability gap with the reason).
- [ ] AC#4: the `# lazy-import:` annotation count equals the pre-PR baseline of 11 (expected delta: zero).
- [ ] AC#7: the revised L0–L9 layer map (with `resources` at L4 below the service group and `schemas` at L3) is recorded in `issue-633-layer-map.md`, and the `check_module_boundaries.py` docstring reflects the three now-enforced boundaries; the #633 comment is drafted (not auto-posted) and surfaced to the user.

---
task_id: "T05"
title: "Add CI guard for MUT patches, document convention, file follow-ups"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#7", "AC#1", "AC#3", "AC#4", "AC#6", "AC#7"]
---

## Summary
Capstone task. Add `tools/check_internal_patches.py` — a CI guard that scans the seven in-scope files for reassignment/`patch.object` of the prohibited MUT symbols and fails unless the line carries a `# boundary-exempt:` annotation. Wire it into the lint workflow, document the convention in `tests/TESTING.md`, and file the follow-up issue/note for deferred work. Lands last (after all conversions) so the guard passes on a fully converted/annotated tree rather than failing CI mid-refactor.

## Target Files
- create: `tools/check_internal_patches.py` — the guard script
- modify: `.github/workflows/lint.yml` — add a step running the guard
- modify: `tests/TESTING.md` — document the MUT-vs-collaborator rule and `# boundary-exempt:` convention
- read: `tools/frontend/check_undefined_css_refs.py` — pattern to mirror (exemption list, exit codes, output)
- read: all seven in-scope test files — to confirm the guard passes after T02–T04
- read: `design/specs/075-mock-at-boundaries-test-refactor/tasks/context.md`
- read: `design/specs/075-mock-at-boundaries-test-refactor/design.md`

## Prompt
1. **Write `tools/check_internal_patches.py`** mirroring the structure of the existing `tools/frontend/check_*.py` guards (module docstring describing prohibited symbols + the exemption annotation; `main()` returning a nonzero exit on violations; clear `file:line — symbol` output). It must:
   - Scan only the seven in-scope files (list them explicitly in the script): `tests/integration/test_websocket_service.py`, `tests/unit/core/test_ws_connection_state.py`, `tests/unit/core/test_websocket_readiness_events.py`, `tests/integration/test_state_proxy.py`, `tests/unit/core/test_app_lifecycle_service.py`, `tests/unit/core/test_app_lifecycle_service_operations.py`, `tests/integration/test_apps.py`.
   - Flag any reassignment (`<obj>.<sym> = ...`) or `patch.object(<obj>, "<sym>")` / `patch("...<sym>")` of a prohibited symbol on a real service/proxy/lifecycle object. The prohibited-symbol set is the enumeration in context.md ("Prohibited-symbol enumeration") / design.md `## Architecture → Guard scope and the dual-role principle`. Copy that list into the script as the canonical source.
   - Treat a line (or its immediately preceding line) carrying `# boundary-exempt:` as exempt — this is the per-site human classification. `task_bucket.spawn` is NOT in the prohibited set (different object).
   - Be a line/pattern scanner (regex over file text) like the sibling CSS guards — it does not need full AST parsing; mirror their approach.
2. **Wire into `.github/workflows/lint.yml`**: add a step `run: uv run python tools/check_internal_patches.py` alongside the existing `tools/frontend/check_*.py` steps (~lines 145–160), under the same `needs.changes.outputs.python` gate.
3. **Run it locally** (`uv run python tools/check_internal_patches.py`) and confirm it passes against the converted tree from T02–T04. If it flags an un-annotated patch, that patch is either a missed conversion (fix it) or a legitimate collaborator stub (add the `# boundary-exempt:` annotation) — do not loosen the guard to make it pass.
4. **Document in `tests/TESTING.md`**: add a subsection covering the MUT-vs-collaborator rule, the `fake_session`/`build_fake_ws` boundary pattern, the `# boundary-exempt: collaborator of <MUT>` annotation convention, and a pointer to the guard script.
5. **File follow-ups (AC#7)** using `gh-issue` (run `gh-issue overview` first for conventions): one tracking issue for the scheduler `__new__` doubles in `test_scheduler_service_reschedule.py`; and a note (issue or a short appendix in the design doc) recording the deferred Cluster D and Cluster E/F items. Apply repo label conventions (`type:`, `area:testing`, `size:`).

## Focus
- Lint workflow runs Python guards as `uv run python tools/frontend/check_*.py` steps gated on `needs.changes.outputs.python == 'true' || workflow_dispatch` (`.github/workflows/lint.yml:145–160`). Add the new step in the same block so it runs on Python changes.
- The closest sibling to copy is `tools/frontend/check_undefined_css_refs.py` (has an `EXEMPTIONS` mechanism) — model the exemption handling and exit-code/output style on it.
- This task MUST run after T02–T04: the guard would fail CI if any in-scope file still has un-annotated MUT patches. That is also AC#1's verification — the guard passing IS the proof that no MUT patches remain unannotated.
- Do not make the guard so strict it flags legitimate annotated collaborator stubs (the `# boundary-exempt:` escape must work) nor so loose it misses real MUT patches — test it against the converted files.
- `tests/TESTING.md` is ~497 lines with a clear sectioned structure; add the new subsection under the mock-strategy guidance.

## Verify
- [ ] FR#7: `tools/check_internal_patches.py` exists, scans the seven in-scope files for the enumerated prohibited symbols, honors `# boundary-exempt:` annotations, and is wired into `.github/workflows/lint.yml`.
- [ ] AC#1: `uv run python tools/check_internal_patches.py` passes — no in-scope test reassigns/`patch.object`-patches its MUT among the prohibited symbols without a `# boundary-exempt:` annotation.
- [ ] AC#3: `uv run pytest tests/unit tests/integration` is green across the whole suite (final all-green gate after T01–T04 conversions).
- [ ] AC#4: The `system` and `e2e` CI jobs are green on the PR branch (the hard merge gate — these exercise the real aiohttp/HA boundaries the converted unit tests mock; confirmed after all conversions land, not assumed from general CI policy).
- [ ] AC#6: The guard exists and is wired into `.github/workflows/lint.yml`; running it locally passes.
- [ ] AC#7: A tracking issue exists for the scheduler `__new__` doubles, and a follow-up note records the deferred Cluster D / E / F items.

---
task_id: "T01"
title: "Relocate build_fake_ws to test_utils and fix test_history vacuous stub"
status: "done"
depends_on: []
implements: ["FR#6", "AC#2"]
---

## Summary
Foundational prep that lands two small, independent, low-risk changes early. (1) Move the `build_fake_ws()` helper out of `tests/integration/test_websocket_service.py` into `src/hassette/test_utils/` so the WebsocketService unit tests in `tests/unit/core/` can import it during the later Cluster A work. (2) Fix the vacuous `normalize_history` stub at `test_history.py:78` — one of issue #1036's five named spots. Both keep the suite green and unblock later tasks.

## Target Files
- modify: `tests/integration/test_websocket_service.py` — remove the local `build_fake_ws` definition; import it from `test_utils`
- create: `src/hassette/test_utils/ws_mocks.py` — new home for `build_fake_ws()` (or place in an existing suitable module — see Focus)
- modify: `src/hassette/test_utils/__init__.py` — export `build_fake_ws` if the package re-exports helpers (check existing convention)
- modify: `tests/integration/test_history.py` — line 78 `return_value`→`side_effect`
- read: `design/specs/075-mock-at-boundaries-test-refactor/tasks/context.md`
- read: `design/specs/075-mock-at-boundaries-test-refactor/design.md`

## Prompt
Two independent changes; keep them as two logical commits or clearly separated edits.

**Part A — relocate `build_fake_ws()`:**
1. Find the `build_fake_ws()` definition in `tests/integration/test_websocket_service.py`. Read it in full and note every name it depends on (imports, module-level helpers).
2. Move the definition into `src/hassette/test_utils/`. Prefer a new module `ws_mocks.py` (cohesive with the existing `web_mocks.py`/`mock_hassette.py` naming). If `src/hassette/test_utils/__init__.py` re-exports helpers (read it first to confirm the convention), add `build_fake_ws` to the exports.
3. In `test_websocket_service.py`, delete the local definition and import `build_fake_ws` from its new location. Do not change any call sites' behavior.
4. Confirm `build_fake_ws` is the ONLY symbol you move — do not relocate `fake_session` construction or anything else.

**Part B — fix `test_history.py:78`:**
1. Read `tests/integration/test_history.py` lines ~60–91 (the `test_minimal_history_differs_if_not_normalized` test).
2. At line 78, change `mock_normalize.return_value = lambda x: x` to `mock_normalize.side_effect = lambda x: x`. This makes the patched `normalize_history(data)` return `data` unchanged (identity) instead of returning a lambda object.
3. Do NOT change the test's structure: only the minimal-flag call (inside the `with patch(...)` block) is patched; the non-minimal call above it runs real code outside the patch. Leave that as-is.

Run the affected test files after each part and confirm green. See design.md `## Architecture → Sequencing` (steps 0 and 1) and the Convention Examples.

## Focus
- `build_fake_ws` is currently referenced only in `tests/integration/test_websocket_service.py` (verified — no other importers today), so the relocation has a single update site now; later tasks add imports in the unit test files.
- `src/hassette/test_utils/__init__.py` is 3.8 KB and likely re-exports the public helper surface — read it to match the export style (the unit tests import from `hassette.test_utils`, per `tests/TESTING.md`).
- Do NOT enrich `build_fake_ws()` with auth-handshake or recv-sequence scripting in this task — it stays a thin aiohttp stub (Key Decision 4). Enrichment, if any, is decided per-test during Cluster A.
- The `test_history.py` current form passes vacuously: `normalize_history(data)` returns a lambda, so the `history_with_minimal_flag != history_without_minimal_flag` assertion is trivially true. The `side_effect` form makes the minimal response flow through un-normalized so the inequality is meaningful.
- This is core test infrastructure; per CLAUDE.md, run the changed test files locally before committing.

## Verify
- [ ] FR#6: `test_history.py:78` uses `side_effect=lambda x: x` (no `return_value = lambda` remains for `normalize_history`); the test's two-call structure is unchanged.
- [ ] AC#2: `uv run pytest tests/integration/test_history.py` passes, and reading the test confirms the inequality assertion now exercises real un-normalized data rather than passing vacuously; `build_fake_ws` is importable from `hassette.test_utils` and `tests/integration/test_websocket_service.py` imports it (no local definition remains), with that file's tests still green.

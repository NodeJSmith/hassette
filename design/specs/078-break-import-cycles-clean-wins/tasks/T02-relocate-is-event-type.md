---
task_id: "T02"
title: "Relocate is_event_type to events, add utils->events RULE"
status: "done"
depends_on: ["T01"]
implements: ["FR#5", "FR#6", "FR#7", "AC#3"]
---

## Summary
Move `is_event_type` from `src/hassette/utils/type_utils.py` into `src/hassette/events/`, and drop the now-unused `from hassette.events import Event` from `type_utils.py`. `is_event_type` is the only thing in `utils` that imports `events`, so this removes the `utils → events` edge, leaving the correct one-directional `events → utils`. Update the one `src/` caller (`bus/extraction.py`) and the test file that exercises it. Then add the boundary RULE forbidding `utils` from importing `hassette.events`. Functionally independent of T01, but ordered after it so each task's append to the shared `tools/check_module_boundaries.py` lands on a green base.

## Target Files
- modify: `src/hassette/utils/type_utils.py` (remove `is_event_type` and the `from hassette.events import Event` import)
- modify: `src/hassette/events/__init__.py` (export `is_event_type`) OR create `src/hassette/events/type_checks.py`
- create: `src/hassette/events/type_checks.py` (only if you choose a dedicated module over placing it beside the Event base)
- modify: `src/hassette/bus/extraction.py` (line 7 import path)
- modify: `tests/integration/test_type_detection.py` (line 17 import path)
- modify: `tools/check_module_boundaries.py` (append the utils->events Rule)
- read: `src/hassette/events/base.py` (where the `Event` base lives)
- read: `design/specs/078-break-import-cycles-clean-wins/design.md` (Architecture → Change 3; Change 4)
- read: `design/specs/078-break-import-cycles-clean-wins/tasks/context.md`

## Prompt
Read `context.md` and the design doc's `## Architecture` → "Change 3" and "Change 4" sections.

1. **Move the function.** Cut `is_event_type` (and only that function — `type_utils.py:240-263`) from `src/hassette/utils/type_utils.py` and place it in `events/`. Preferred home: a small `src/hassette/events/type_checks.py` next to the `Event` base (`events/base.py`), re-exported from `events/__init__.py` so `from hassette.events import is_event_type` works. If a single obvious existing module in `events/` is the natural home, that is acceptable too — keep it importable as `hassette.events.is_event_type`. Preserve the function's docstring verbatim (it documents the no-Union/Optional limitation).
2. **Remove the dead import.** Delete `from hassette.events import Event` (line 10) from `type_utils.py` — after the move it is unused there. Confirm no other symbol in `type_utils.py` references `Event`.
3. **Repoint callers** to `from hassette.events import is_event_type`:
   - `src/hassette/bus/extraction.py:7` (it currently imports `get_type_and_details, is_annotated_type, is_event_type, normalize_annotation` from `hassette.utils.type_utils` — split the import so `is_event_type` comes from `events` and the rest stays from `utils.type_utils`).
   - `tests/integration/test_type_detection.py:17` (this file calls `is_event_type` many times — update the import only, not the calls).
4. **Add the boundary RULE.** Append a `Rule` to `RULES` in `tools/check_module_boundaries.py` (all four fields):
   - `name`: e.g. `"utils-no-events"`
   - `applies=lambda layer: layer == "utils"`
   - `forbids=lambda module: module == "hassette.events" or module.startswith("hassette.events.")`
   - `reason`: one line — `utils` sits below `events`; the only upward dependency (`is_event_type`) has moved.

## Focus
- `is_event_type` uses `inspect.isclass(base_type) and issubclass(base_type, Event)` — it needs the `Event` base symbol. In its new `events/` home, import `Event` from `events/base.py` (a sibling — no cycle).
- `bus/extraction.py:40,52` call `is_event_type`; do not change call sites, only the import source.
- `events/hassette.py:7` imports `get_traceback_string` from `utils` — that `events → utils` edge is correct and stays. Do not remove it.
- After the move, `grep -rn "from hassette.events" src/hassette/utils` must return nothing (FR#6).
- Watch for any other in-`utils` references to `Event` before deleting the import — there should be none, but confirm.

## Verify
- [ ] FR#5: `from hassette.events import is_event_type` succeeds; `bus/extraction.py` and `tests/integration/test_type_detection.py` import it from `hassette.events`; `is_event_type` no longer defined in `utils/type_utils.py`.
- [ ] FR#6: `grep -rn "from hassette.events\|import hassette.events" src/hassette/utils` returns nothing.
- [ ] FR#7: `tools/check_module_boundaries.py` `RULES` contains a `utils`-layer rule forbidding `hassette.events[.*]`, all four fields populated.
- [ ] AC#3: inserting a throwaway top-level `from hassette.events import Event` into any `utils/` file makes `python tools/check_module_boundaries.py` exit non-zero; the clean tree exits zero. `uv run pyright` reports zero new errors and `uv run pytest tests/integration/test_type_detection.py` passes.

---
task_id: "T02"
title: "Add bus-no-core boundary guard rule and tests"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "AC#1", "AC#2"]
---

## Summary

Lock in the cycle break from T01 by adding a `bus-no-core` rule to
`tools/check_module_boundaries.py`, structured identically to the existing
`api-no-core` rule, so any future runtime `bus → core` import fails pre-push/CI.
Update the tool's module docstring to move `bus ↔ core` from the "remaining
cycles" list into the enforced-boundaries list, and extend the boundary-tool
unit tests: adapt the now-incorrect "not yet governed" assertion and add a
positive `bus-no-core` test plus a `TYPE_CHECKING`-exempt test. Because T01
already removed the only runtime `bus → core` import, the new rule passes
immediately on the real tree.

## Target Files

- modify: `tools/check_module_boundaries.py`
- modify: `tests/unit/tools/test_check_module_boundaries.py`
- read: `design/specs/080-break-bus-core-import-cycle/design.md`

## Prompt

Implement the lock-in guard described in the design doc's `## Architecture`
("The lock-in guard") and `## Test Strategy` sections.

1. **Add the rule.** In `tools/check_module_boundaries.py`, append a `Rule` to
   the `RULES` list, mirroring `api-no-core` exactly:

   ```python
   Rule(
       name="bus-no-core",
       applies=lambda layer: layer == "bus",
       forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
       reason="bus must not import core at runtime; core sits above the service layer (#1089)",
   )
   ```

2. **Update the module docstring** (the "Boundaries enforced today" list around
   lines 13-24 and the "remaining runtime cycles" paragraph): add `bus → core`
   to the enforced list with the `#1089` reference, and remove `bus`↔`core`
   (`InvokeHandler`) from the "remaining runtime cycles" sentence so the docstring
   matches reality. Leave the `scheduler`↔`core` and `state_manager`↔`core`
   entries in the remaining-cycles list (still tracked under #1079).

3. **Adapt the boundary-tool tests** in
   `tests/unit/tools/test_check_module_boundaries.py`:
   - `test_other_cross_layer_imports_not_yet_governed` (currently asserts
     `check_source("from hassette.core import Hassette\n", "bus") == []`) — this
     assertion now flips, because `bus → core` is governed by the new rule.
     Re-point the example to a still-ungoverned layer: use layer
     `"state_manager"` with a source string that reflects what `state_manager`
     actually imports today —
     `check_source("from hassette.core.state_proxy import StateProxy\n", "state_manager") == []`.
     (The `state_manager ↔ core` cycle is out of scope here and tracked under
     #1079, so `state_manager → core` remains allowed today.) Update the comment
     to name `state_manager → core` as the still-ungoverned example, so the test
     stays a realistic pin rather than a fictional one.
   - Add `test_bus_import_of_core_flagged` — assert that
     `check_source("from hassette.core import Hassette\n", "bus")` returns a
     single violation whose message is
     `"bus-no-core: imports hassette.core — bus must not import core at runtime; core sits above the service layer (#1089)"`.
     Mirror the shape of `test_production_import_of_test_utils_flagged`.
   - Add `test_bus_type_checking_core_import_exempt` — assert that a
     `bus → core` import placed inside an `if TYPE_CHECKING:` block returns `[]`,
     mirroring `test_type_checking_import_exempt` but with a `hassette.core`
     import and layer `"bus"`.

4. **Verify:**
   - `uv run pytest tests/unit/tools/test_check_module_boundaries.py -q` — all
     green, including `test_real_src_files_pass`. Also run the broader unit +
     integration suites once before commit (per CLAUDE.md) to confirm the T01
     migration plus this change leave the tree fully green.
   - `python tools/check_module_boundaries.py` exits 0 and its OK line now
     reports one more rule than before T02.
   - **Self-proving check (AC#2):** temporarily revert only the
     `bus/invocation.py` import line from T01 back to
     `from hassette.core.commands import InvokeHandler` (or temporarily point it
     at any `hassette.core` module), run `python tools/check_module_boundaries.py`,
     confirm it now fails with a `bus-no-core` violation, then restore the fix.
     Do not commit the reverted state.

## Focus

- **This task depends on T01.** The rule only passes because T01 removed the
  runtime `bus → core` import. Do not start until T01's tree is green.
- **Rule construction is purely declarative** — the `api-no-core` rule at
  `tools/check_module_boundaries.py:67-72` is the exact template. The `forbids`
  lambda must match both the bare `hassette.core` module and `hassette.core.*`
  submodules.
- **`test_real_src_files_pass`** is a parametrized test that runs the real guard
  over every `src/` file. After T01 + this rule, it must stay green — if it
  fails, there is a runtime `bus → core` import T01 missed; fix that, don't
  weaken the rule.
- **Exact message format matters** for the positive test: the message is
  `f"{rule.name}: imports {module} — {rule.reason}"` (see `check_source`). Copy
  the `reason` string verbatim into the expected assertion.
- **Do not broaden scope** — only the `bus-no-core` rule. The `hassette._*`
  attribute lint and re-enabling other boundaries belong to #1091/#1079.

## Verify

- [ ] FR#4: `check_source("from hassette.core import Hassette\n", "bus")` returns
  a `bus-no-core` violation (asserted by `test_bus_import_of_core_flagged`).
- [ ] FR#5: `python tools/check_module_boundaries.py` exits 0 on the post-fix
  tree and `test_real_src_files_pass` passes.
- [ ] AC#1: `python tools/check_module_boundaries.py` exits 0 and its OK summary
  reports one additional rule versus before this task.
- [ ] AC#2: reverting only the `invocation.py` import fix makes
  `python tools/check_module_boundaries.py` fail with a `bus-no-core` violation;
  restoring it returns the guard to green.

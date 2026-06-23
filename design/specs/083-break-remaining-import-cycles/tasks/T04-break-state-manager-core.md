---
task_id: "T04"
title: "Break state_manager <-> core cycle via StateReader"
status: "planned"
depends_on: ["T01"]
implements: ["FR#4", "FR#7", "AC#1", "AC#3", "AC#5", "AC#6"]
---

## Summary
Remove the runtime `from hassette.core.state_proxy import StateProxy` import in `state_manager/state_manager.py` (line 10) by retyping `DomainStates`/`StateManager` against the read-only `StateReader` protocol from T01. The instance is unchanged — `StateManager._state_proxy` still returns `self.hassette.state_proxy` (line 244). Mirror the retype in the companion type stub `state_manager.pyi`. Add a `state_manager-no-core` rule to the boundary checker, flip the existing "not yet governed" stand-in test, add a `DomainStates`-against-a-fake-`StateReader` test (the testability payoff), and finalize the boundary-checker docstring. This is the last task, so it also verifies the whole-tree rule count.

## Target Files
- modify: `src/hassette/state_manager/state_manager.py`
- modify: `src/hassette/state_manager/state_manager.pyi`
- modify: `tools/check_module_boundaries.py`
- modify: `tests/unit/tools/test_check_module_boundaries.py`
- create: `tests/unit/state_manager/test_domain_states_statereader.py`
- read: `src/hassette/types/__init__.py`
- read: `design/specs/083-break-remaining-import-cycles/design.md`

## Prompt
Follow the design doc `## Architecture → Step 2 — the two core cycles` (the `core ↔ state_manager` paragraph).

In `src/hassette/state_manager/state_manager.py`:
1. Delete the runtime import `from hassette.core.state_proxy import StateProxy` (line 10).
2. Add `StateReader` to the existing runtime import `from hassette.types import StateT` (line 15) → `from hassette.types import StateReader, StateT`.
3. Retype `DomainStates.__init__(self, state_proxy: "StateProxy", model: ...)` (line 64) to `state_proxy: "StateReader"`; the stored `self._state_proxy` attribute (line 68) follows the same type.
4. Retype the `StateManager._state_proxy` property return type at line 242: `def _state_proxy(self) -> StateReader:` (was `StateProxy`). Leave the body `return self.hassette.state_proxy` unchanged (line 244).
5. Confirm the four consumed members are all on `StateReader`: `get_state` (lines 109, 351), `yield_domain_states` (line 159), `num_domain_states` (line 170), `__contains__` via `in` (line 176). No other `StateProxy` members are accessed. Also note line 323 (`DomainStates[StateT](self._state_proxy, model)` in `StateManager.__getitem__`) passes `self._state_proxy` into `DomainStates.__init__` — after the retype both sides are `StateReader`, so it stays consistent; no change needed there beyond the annotations in steps 3–4.

In `src/hassette/state_manager/state_manager.pyi` (the companion stub — found in the plan gap check):
1. Replace `from hassette.core.state_proxy import StateProxy` (line 28, in the TYPE_CHECKING block) with `from hassette.types import StateReader`.
2. Retype `DomainStates._state_proxy: StateProxy` (line 37), `DomainStates.__init__(self, state_proxy: StateProxy, ...)` (line 43), and `StateManager._state_proxy(self) -> StateProxy` (line 60) to `StateReader`.

In `tools/check_module_boundaries.py`:
1. Append a `Rule` to `RULES` (copy the `bus-no-core` shape):
   ```python
   Rule(
       name="state_manager-no-core",
       applies=lambda layer: layer == "state_manager",
       forbids=lambda module: module == "hassette.core" or module.startswith("hassette.core."),
       reason="state_manager must not import core at runtime; StateProxy is consumed via StateReader (#1079)",
   ),
   ```
2. Finalize the module docstring (lines 13–24): add `state_manager-no-core` to the enforced-rules list, and remove `state_manager ↔ core` from the "deferred to an ADR" paragraph. After this task only `conversion ↔ models` (#892) remains in that paragraph — rewrite it to state the two service-layer cycles are resolved via protocol inversion (`SchedulerServiceProtocol`, `StateReader`) and only `conversion ↔ models` (#892) is still open.

In `tests/unit/tools/test_check_module_boundaries.py`:
1. Flip `test_state_manager_import_of_core_not_yet_governed` (line 144): rename it (e.g. `test_state_manager_import_of_core_flagged`) and change the assertion from `== []` to expect the `state_manager-no-core` violation message. Update the module docstring at the top of the test file (line 7) which currently says "Still-ungoverned cross-layer imports (e.g. state_manager → core) are allowed" — that example is no longer ungoverned.
2. Add a submodule-import variant if it parallels the `bus` tests.

Create `tests/unit/state_manager/test_domain_states_statereader.py`:
1. Define a minimal dict-backed fake implementing `StateReader` (`get_state`, `num_domain_states`, `yield_domain_states`, `__contains__`).
2. Construct `DomainStates` with the fake and a real state model class; assert `get`, `__contains__`, `__len__`, and iteration work — proving the public state path no longer needs the concrete `StateProxy` or `core`.

## Focus
- `state_manager/state_manager.py:10` is the ONLY runtime `hassette.core` import in the `state_manager` package (verified). The `.pyi:28` import is TYPE_CHECKING-only and `.pyi` files are not scanned by the boundary checker, but retype it anyway for type-surface consistency.
- `state_manager.py` already imports `from hassette.types import StateT` (line 15, runtime), so `state_manager → types` is established — adding `StateReader` is free.
- The `StateManager._state_proxy` property return annotation (line 242) evaluates at definition time (no `from __future__`), so `StateReader` must be a runtime import (step 2), not TYPE_CHECKING.
- Integration tests that construct a real `StateProxy` and pass it into `DomainStates` (`tests/integration/test_states.py`) need no change — `StateProxy` satisfies `StateReader` structurally.
- Depends on T01 (`StateReader` must exist/export). Best sequenced after T02 and T03 so the docstring rewrite reflects all three landed rules and AC#1's rule count is final — set `depends_on: ["T01"]` but run last in the orchestration order.
- The boundary checker lives at `tools/check_module_boundaries.py` (repo root). Its OK summary string (line 304) prints `len(RULES)` — after all tasks land it should read 8 import rules (5 existing + scheduler-no-core + state_manager-no-core + resources-no-task_bucket).

## Verify
- [ ] FR#4: `grep -n "hassette.core" src/hassette/state_manager/state_manager.py` shows no runtime import; `DomainStates`/`StateManager` are typed against `StateReader` in both `.py` and `.pyi`; pyright passes.
- [ ] FR#7: `tools/check_module_boundaries.py` `RULES` contains `state_manager-no-core` forbidding `hassette.core` for the `state_manager` layer.
- [ ] AC#1: `python tools/check_module_boundaries.py` reports zero violations and its summary names 8 import rules (the three new rules present).
- [ ] AC#3: `state_manager/state_manager.py` contains no runtime `hassette.core` import.
- [ ] AC#5: `tests/unit/state_manager/test_domain_states_statereader.py` passes — `DomainStates` works against a dict-backed fake `StateReader` with no `StateProxy`/`core` dependency.
- [ ] AC#6: the flipped `test_state_manager_import_of_core_*` test asserts `from hassette.core.state_proxy import StateProxy` in a `state_manager` file is flagged by `state_manager-no-core`.

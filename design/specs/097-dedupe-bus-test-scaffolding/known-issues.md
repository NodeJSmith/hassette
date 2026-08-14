# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Timing-constant docstring convention differs from its sibling files in the same package

Status: open
Run: 87
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: tests/integration/bus/test_bus_error_handler_combos.py
Affected files:
- tests/integration/bus/test_bus_error_handler_combos.py
- tests/integration/bus/conftest.py
- tests/integration/bus/test_bus_immediate.py
- tests/integration/bus/test_bus_duration.py

Issue:
`test_bus_error_handler_combos.py` documents its module-level timing constants (`ERROR_TIMEOUT`,
`DURATION_ERROR_TIMEOUT`) with a PEP-257 attribute docstring on the line below the assignment,
while every sibling file in the same `tests/integration/bus/` package (`conftest.py`,
`test_bus_immediate.py`, `test_bus_duration.py`) documents the same kind of constant with a
trailing inline `#` comment on the assignment line itself. Both styles are internally consistent
within their own file, but the package as a whole has two competing conventions for the same
concept.

Why deferred:
Fixing this cleanly means picking one convention and applying it across all four files, including
three files (`conftest.py`, `test_bus_immediate.py`, `test_bus_duration.py`) that already passed a
prior clean-code review pass in this same branch — editing them again for a purely cosmetic,
package-wide style call is scope creep beyond this run's diff-focused review (T06 only touched
`test_bus_error_handler_combos.py`'s trigger lines) and beyond this run's own touched files. There's
no correctness or readability risk today; each file reads clearly on its own.

Recommended follow-up:
Next time any of these four files is touched for an unrelated reason, pick one convention (inline
`#` comment matches 3 of 4 files today, so it's the natural default) and apply it to the fourth
file's constants in the same pass. Not worth a dedicated PR on its own.

Acceptance criteria:
- All timing/timeout constants in `tests/integration/bus/*.py` use the same documentation style
  (either all trailing `#` comments or all attribute docstrings).

## KI-002: Four on_error passthrough tests in test_bus_error_handler_combos.py are near-identical and a parametrize candidate

Status: resolved — decision recorded, not fixed via parametrize
Run: 87
Source: clean-code
Reason not fixed now: needs-decision
Observed in: tests/integration/bus/test_bus_error_handler_combos.py
Affected files:
- tests/integration/bus/test_bus_error_handler_combos.py

Issue:
`test_on_homeassistant_start_on_error_passthrough`, `test_on_hassette_service_failed_on_error_passthrough`,
`test_on_websocket_connected_on_error_passthrough`, and `test_on_app_running_on_error_passthrough`
(lines 443-533) share an identical shape: same `_ErrorCollector`, same inner `App` subclass pattern
(one delegate registration with `on_error=self.on_err`, a handler that raises `ValueError`, and an
`on_err` that forwards to the collector), same `async with AppTestHarness(...) as harness: await
harness.simulate_*(); await errors.wait(); await settle()` tail — differing only in which delegate,
simulate method, handler method, and event type is used. This is a plausible
`pytest.mark.parametrize` candidate over `(delegate_name, simulate_method, handler_method,
event_type)`.

Why deferred:
Collapsing four standalone tests into one parametrized test changes failure-message granularity
(a single parametrized test's failure ID is less immediately readable than a dedicated function
name per Shape B delegate) and touches test structure, not just formatting — the kind of change
`refactoring-discipline.md` treats as needing a pin-behavior-first pass, not a mechanical nitpick
fix. Whether the four-test-function shape or one parametrized test is more readable for this
specific "prove passthrough reaches all 4 delegates" intent is a judgment call for whoever owns
this file's test-authoring conventions, not something to decide unilaterally inside a style pass.

Recommended follow-up:
Evaluate whether to convert the four passthrough tests to
`@pytest.mark.parametrize("delegate_name, simulate_method, handler_method, event_type", [...])`
over a single test body, or leave them as four named functions (current shape trades duplication
for self-documenting test names / independently-skippable tests).

Acceptance criteria:
- A decision is recorded (parametrize, or explicitly keep as four functions) and, if parametrize is
  chosen, all four cases still exercise the same delegate/simulate/handler/event combinations with
  equivalent assertions.

Resolution:
Decided to keep as four separate functions — the three-axis variation (registration method, handler
signature, `simulate()` arity) means a clean parametrize would need a per-case handler-builder
function anyway, trading this file's direct "this exact primary call reaches this exact handler"
readability for a marginal duplication win. The duplication is now explicitly marked as intentional
via `# dup-ignore-start: KI-002` / `# dup-ignore-end` wrapping all four functions in
`test_bus_error_handler_combos.py` (confirmed via `tools/check_duplicate_code.py`: the 4-fragment
cluster no longer appears in its output).

# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: StateReader.num_domain_states and __contains__ are now orphaned on StateProxy

Status: open
Run: 58
Source: T06
Reason not fixed now: needs-decision
Observed in: T06 (3 review iterations — code review PASS, integration review WARN all 3 times on this finding)
Affected files:
- src/hassette/types/types.py:280 (`StateReader.num_domain_states`)
- src/hassette/types/types.py:284 (`StateReader.__contains__`)
- src/hassette/core/state_proxy.py:317 (`StateProxy.num_domain_states`)
- src/hassette/core/state_proxy.py:421 (`StateProxy.__contains__`)

Issue:
T06 changed `DomainStates.__len__` and `DomainStates.__contains__` in
`src/hassette/state_manager/state_manager.py` to compute membership by iterating
`yield_domain_states()`/`get_state()` and checking `_validate_if_member` (predicate AND
convertibility), instead of delegating to `StateProxy.num_domain_states()` /
`StateProxy.__contains__()`. That delegation was the only production call site for those two
`StateReader` Protocol members. Verified directly (not just via prior review passes): grepping
`num_domain_states` and `StateReader.__contains__`-style usage across `src/` and `tests/` turns up
zero non-test callers of `StateProxy.num_domain_states` or `entity_id in state_proxy`/`__contains__`
on `StateProxy` outside its own definition. `state_manager.py`'s only remaining proxy calls are
`yield_domain_states()` and `get_state()`. The two Protocol methods and their `StateProxy`
implementations are dead code in production as of this change.

Why deferred:
Fixing this requires an architectural decision that isn't T06's (or spec 093's) to make: whether to
keep `num_domain_states`/`__contains__` on the `StateReader` Protocol and `StateProxy` for
potential future or external `StateReader` implementers (the Protocol's own docstring says it
"describes the four members state-manager consumers call on the state proxy" — that description
is now stale either way), or remove both Protocol members and their `StateProxy` implementations
as dead code. Both files are outside T06's declared scope (design.md bounds T06 to
`state_manager.py` + `exceptions.py`) and outside T07's and T08's `modify:` scope as well — neither
task claims `types/types.py` or `core/state_proxy.py` for write access, only `read:`. This is
purely dead internal framework code with zero callers; it does not affect any running behavior, so
it does not trip the known-issues Severity Gate (no user-visible breakage, no data loss, no
security exposure, no blocked workflow).

Recommended follow-up:
Decide keep-vs-remove for `StateReader.num_domain_states`/`__contains__` and the corresponding
`StateProxy` methods:
- If keeping (e.g., for a documented external-implementer use case): update the `StateReader`
  docstring to stop claiming these are called by state-manager consumers, and add a test or comment
  explaining who is expected to call them.
- If removing: delete both Protocol members from `StateReader` in `src/hassette/types/types.py`,
  delete `StateProxy.num_domain_states` and `StateProxy.__contains__` in
  `src/hassette/core/state_proxy.py`, and update `tests/unit/types/test_service_protocols.py` (which
  asserts `StateProxy` has every `StateReader` member) and
  `tests/unit/state_manager/test_domain_states_statereader.py` /
  `test_domain_states_membership.py` (whose fake `StateReader` implementations currently include
  these two methods) accordingly.

Acceptance criteria:
- A decision is recorded (ADR, issue comment, or code comment) on whether `StateReader.num_domain_states`/`__contains__` are kept or removed.
- If removed: no references to `StateProxy.num_domain_states` or `StateProxy.__contains__` remain in `src/` or `tests/`, and the `StateReader` Protocol no longer declares them.
- If kept: `StateReader`'s docstring and any relevant tests reflect the actual (non-state-manager) caller this is being kept for.

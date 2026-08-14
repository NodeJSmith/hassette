---
task_id: "T06"
title: "Extract shared state-transition-trigger helper and adopt in test_bus_duration.py, test_bus_error_handler_combos.py"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#11", "AC#2"]
---

## Target Files

- modify: `tests/integration/bus/helpers.py`
- modify: `tests/integration/bus/test_bus_duration.py`
- investigated, not modified: `tests/integration/bus/test_bus_immediate.py` — the `send_state_change`+`seed`
  pair this task targets never occurs there; every `seed()` call is a standalone registration-time
  snapshot (see FR#11's descope note in design.md)
- modify: `tests/integration/bus/test_bus_error_handler_combos.py`
- modify: `tests/integration/bus/CLAUDE.md`

## Prompt

A post-T05 re-run of `uv run python tools/check_duplicate_code.py` found residual duplication
clusters that FR#1-#8 never targeted. Most of them share one shape, repeated across
`test_bus_duration.py`, `test_bus_immediate.py`, and `test_bus_error_handler_combos.py`: after
registering a listener, tests drive the state transition with:

```python
await send_state_change(harness, "light.kitchen", "off", "on")
await seed(harness, "light.kitchen", "on")
```

(Both `send_state_change` and `seed` already live in `tests/integration/bus/helpers.py` — see its
module docstring and `tests/integration/bus/CLAUDE.md`.) This exact pair — same entity, `to_state`
argument shared between both calls — repeats many times across these three files. FR#1's
`make_collector` already addressed the *response-collection* side (list+Event+handler); this pair
is the *registration/trigger* side, never targeted before.

Read every occurrence of this pattern across all three files first — some tests do only this one
pair, others (e.g. `test_duration_cancelled_on_state_exit`, `test_duration_resets_on_re_entry` in
`test_bus_duration.py`) drive multiple transitions in sequence (enter → exit → re-enter). Design a
helper that covers the single-pair case cleanly; a multi-transition test can call it more than once
if that reads naturally, or stay inline if forcing it through the helper would obscure the
sequence — match whatever keeps each test's intent readable, the same judgment call T01 already
made for `make_collector`.

Add the helper to `tests/integration/bus/helpers.py` (naming it something like
`enter_state`/`trigger_state_change`/`drive_state_change` — pick whichever reads best next to the
existing `seed`/`send_state_change`/`fire` helpers). Update call sites in all three files to use
it wherever the exact pair appears unchanged.

**`test_bus_error_handler_combos.py` scope note:** this file has its own `_ErrorCollector`
abstraction (around line 38) for the error-context-collection side of its tests — do not touch
that class or its usage (`errors.bound(hassette)`, `errors.wait(...)`, `errors.single(...)`).
Only its `send_state_change`+`seed` trigger lines are in scope for this task, the same lines that
already import `seed, send_state_change` from `.helpers` at the top of the file.

Preserve every test's actual assertions, timeout values, and entity/state arguments exactly — this
is a pure structural refactor, not a test-behavior change.

## Verify

- [ ] FR#11: `tests/integration/bus/helpers.py` has a new state-transition-trigger helper function.
- [ ] FR#11: `test_bus_duration.py`, `test_bus_immediate.py`, and `test_bus_error_handler_combos.py`
      adopt it at every call site where the exact `send_state_change` + `seed` pair (same entity,
      same target state) appears unchanged; document in a comment any remaining occurrence the
      helper genuinely can't cover cleanly.
- [ ] `test_bus_error_handler_combos.py`'s `_ErrorCollector` class and its usages are byte-for-byte
      unchanged (confirm via `git diff` showing only trigger-line changes in that file).
- [ ] `tests/integration/bus/CLAUDE.md` documents the new helper (FR#9's documentation convention
      extends to this helper too).
- [ ] `uv run python tools/check_duplicate_code.py` — the residual clusters that were previously
      confirmed to live entirely inside these three files' pre-T06 diff are gone. (Clusters that
      also touch files outside this design's scope — `test_accessors.py`, `test_predicates.py`,
      `test_predicate_details.py`, `tests/unit/core/test_bus_service_error_handler.py`,
      `test_bus_service_timeout.py` — are out of scope for this task; they remain and that's
      expected.)
- [ ] `uv run pytest tests/integration/bus/test_bus_duration.py tests/integration/bus/test_bus_immediate.py tests/integration/bus/test_bus_error_handler_combos.py -n 4` passes with zero failures.
- [ ] `prek -a` passes clean on every modified file.

# Design: Bus Dispatch and Subscription Decomposition

**Date:** 2026-05-18
**Status:** approved
**Scope-mode:** hold
**Issues:** #783

## Problem

The three longest methods in the bus event dispatch and subscription registration paths each mix multiple concerns into a single method body. The immediate-dispatch method (134 lines) interleaves state validation, duration timer management, predicate evaluation, and handler invocation. The event dispatch method (89 lines) duplicates the duration vs. non-duration branching. The two subscription builder methods (75 and 91 lines) duplicate 30+ lines of predicate construction logic that differs only in which predicate types are instantiated. These are the most-edited methods in the bus module, and their length makes every change risky.

## Goals

- Reduce the three longest bus methods to under 50 lines each, with each extracted helper having a single responsibility
- Eliminate the duplicated predicate-building logic between state change and attribute change subscription builders

## Non-Goals

- #779 (if_exists / idempotent registration) — separate effort, depends on this decomposition landing first
- #529 (list entity IDs / multi-entity subscriptions) — separate effort
- Any new parameters, API changes, or database changes — this is pure refactoring

## User Scenarios

### Sam: Framework Maintainer

- **Goal:** Understand and modify dispatch methods without tracing through 100+ line methods
- **Context:** Debugging a duration timer edge case or adding a new dispatch feature

#### Reading the dispatch flow

1. **Opens the dispatch method**
   - Sees: A ~25-line method that delegates to named helpers
   - Decides: Which helper to dive into based on the code path
   - Then: Reads a focused 20-30 line helper instead of parsing a monolithic method

#### Adding a new dispatch feature

1. **Identifies which helper to modify**
   - Sees: Named helpers with clear single responsibilities
   - Decides: Which helper owns the behavior being changed
   - Then: Modifies a 20-30 line method instead of editing a 134-line method with interleaved concerns

## Functional Requirements

- **FR#1** The immediate-dispatch path delegates state reading, elapsed-time computation, and duration timer management to focused helpers, each with a single responsibility
- **FR#2** The event dispatch path delegates duration timer construction and lifecycle to a focused helper, eliminating inline nested logic
- **FR#3** A shared filtering function serves both state change and attribute change subscription builders, parameterized by listener mode

## Edge Cases

- **Decomposition preserves behavior:** All extracted helpers produce identical results to the inline code they replace. No behavioral change — only structural.
- **Duration timer closure captures:** The extracted timer helpers receive all previously-captured variables as explicit parameters. No implicit closure state.
- **`changed=False` warning in attribute change:** The `changed=False` warning log stays in `on_attribute_change` itself — it is method-specific behavior, not predicate logic, and must not move into the shared predicate builder.
- **Hold predicates gating:** The `hold_preds` list is only populated when `duration is not None`. This gating stays in the calling methods (`on_state_change`, `on_attribute_change`), not in the shared builder — the builder returns hold predicates unconditionally and the caller decides whether to use them.

## Acceptance Criteria

- **AC#1** The immediate-dispatch method is under 50 lines after decomposition, with each extracted helper under 30 lines (FR#1)
- **AC#2** The event dispatch method is under 30 lines after decomposition (FR#2)
- **AC#3** The state change and attribute change subscription builders each under 40 lines, sharing a single filtering function (FR#3)
- **AC#4** All existing bus unit and integration tests pass without modification
- **AC#5** No new parameters, return types, or public API changes are introduced

## Key Constraints

- Decomposition is pure refactoring — no behavioral changes, no API changes, no new parameters.
- The extracted helpers are module-level functions (no `self`) where possible, making them independently testable.
- No new tests are required — the existing test suite is the behavioral contract. If any test fails, the extraction is wrong.

## Dependencies and Assumptions

- PR #782 has merged, shipping #438 (ListenerOptions), #554 (registration_task on Subscription), and related test cleanup.

## Architecture

### Phase 1: `_immediate_fire_task` Decomposition

Extract three helpers from `bus_service.py`:

1. **`read_current_state`** (module-level function) — wraps the StateProxy read with `ResourceNotReadyError` and generic exception handling. Returns `HassStateDict | None`. Currently at lines 335-350.

2. **`compute_elapsed`** (module-level function) — calculates elapsed time since last state change for duration listeners. Takes `current_state` and `duration_config`, returns `float`. Currently at lines 364-380.

3. **`start_remaining_duration_timer`** (method on BusService) — extracts the `on_duration_fire_immediate` nested closure (lines 391-412) and the timer start call. Takes `listener`, `entity_id`, `duration_config`, `invoke_fn`, `remaining` as explicit parameters, replacing the closure captures.

After extraction, `_immediate_fire_task` becomes: validate entity_id → `read_current_state` → build synthetic event → check predicate → build invoke_fn → branch on duration (call `start_remaining_duration_timer`) vs. non-duration (dispatch). Target: ~45 lines.

### Phase 2: `_dispatch` Decomposition

Extract one helper:

1. **`start_duration_timer`** (method on BusService) — extracts the `on_duration_fire` nested closure (lines 624-656) and the timer start call. Structurally parallel to `start_remaining_duration_timer` but without `override_duration`.

After extraction, `_dispatch` becomes: build invoke_fn → check cancelled → branch on duration (call `start_duration_timer`) vs. non-duration (dispatch + once-removal). Target: ~25 lines.

### Phase 3: Predicate Builder Deduplication

Extract a module-level function in `bus.py`:

```python
def build_change_preds(
    entity_id: str,
    *,
    mode: Literal["state", "attribute"],
    attr: str | None = None,
    changed: bool | ComparisonCondition,
    changed_from: Any,
    changed_to: Any,
) -> tuple[list[Predicate], list[Predicate]]:
```

Returns `(preds, hold_preds)`. The function maps `mode` to the correct predicate classes: `P.StateDidChange` vs. `P.AttrDidChange`, `P.StateFrom` vs. `P.AttrFrom`, etc. The `changed=False` warning log stays in `on_attribute_change` itself (it's method-specific behavior, not predicate logic).

Both `on_state_change` and `on_attribute_change` call this function and pass the results to `_subscribe`. Target: each method under 40 lines.

## Convention Examples

### Scheduler if_exists collision handling (reference for future #779)

**Source:** `src/hassette/scheduler/scheduler.py:164-221`

```python
def add_job(self, job: "ScheduledJob", *, if_exists: Literal["error", "skip", "replace"] = "error") -> "ScheduledJob":
    existing = self._jobs_by_name.get(job.name)
    if existing is not None:
        if if_exists == "skip" and existing.matches(job):
            return existing
        if if_exists == "skip":
            changed_fields = existing.diff_fields(job)
            raise ValueError(
                f"A job named '{job.name}' already exists but its configuration has changed "
                f"(changed fields: {', '.join(changed_fields)})"
            )
        raise ValueError(f"A job named '{job.name}' already exists ...")
    self._jobs_by_name[job.name] = job
```

### Natural key computation

**Source:** `src/hassette/bus/bus.py:270-281`

```python
def _listener_natural_key(self, listener: "Listener") -> tuple[str, int, str, str, str]:
    human_description = P.summarize_top_level(listener.predicate) if listener.predicate else ""
    return (
        listener.identity.app_key,
        listener.identity.instance_index,
        listener.identity.handler_name,
        listener.topic,
        listener.identity.name if listener.identity.name is not None else human_description,
    )
```

## Alternatives Considered

**Extract only `_immediate_fire_task`, leave `_dispatch` and predicate builders:** Rejected because `_dispatch` has the same duration/non-duration duplication pattern, and the predicate builders are the easiest win (identical logic, different class names). All three decompositions are independent and low-risk.

**Unify `start_remaining_duration_timer` and `start_duration_timer` into a single method:** Considered but rejected for now. They are structurally parallel but differ in whether `override_duration` is passed and how the timer callback rechecks state. Premature unification would add a boolean flag or parameter that obscures the two distinct use cases. A future pass could unify them if the patterns converge further.

## Test Strategy

- All three phases are pure refactoring — zero new tests needed.
- All existing unit and integration tests must pass unchanged after each phase.
- Run `tests/unit/bus/`, `tests/integration/test_bus.py`, `tests/integration/test_bus_immediate.py`, `tests/integration/test_bus_duration.py` after each phase.
- If any test fails, the extraction is wrong — do not modify the test.

## Documentation Updates

None — pure internal refactoring with no user-facing changes.

## Impact

**Files modified:**
- `src/hassette/core/bus_service.py` — decompose `_immediate_fire_task` and `_dispatch` into focused helpers
- `src/hassette/bus/bus.py` — extract `build_change_preds` shared predicate builder, simplify `on_state_change` and `on_attribute_change`

**Blast radius:** Low. Internal-only refactoring. No API changes, no new parameters, no database changes. Existing tests are the behavioral contract.

## Open Questions

None — all design decisions resolved during discovery.

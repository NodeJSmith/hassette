---
task_id: "T05"
title: "Migrate test field-access paths and Listener.create() call sites"
status: "planned"
depends_on: ["T01", "T02", "T04"]
implements: ["FR#6", "AC#3"]
---

## Summary
Update all test files that access Listener fields directly through sub-struct paths (~32 field-access sites) and verify all 57 test call sites (plus 5 production call sites) for Listener.create() work with backward-compatible kwargs. This is mechanical migration work — no test logic changes, only field access paths. Also fix the lazy imports in accessors.py (FR#12/AC#12 included here since it's a small isolated fix). Finally, remove the backward-compat property accessors and method forwards added in T01 Step 2b — all consumers now use sub-struct paths directly.

## Prompt
Read the design doc sections "Architecture > Composed Listener" (for the field mapping) and "Fixes included" (for the lazy import fix).

**Step 1: Update test field-access paths.** For each file below, update `listener.field` to `listener.sub_struct.field`:

**tests/unit/bus/test_bus_error_handler.py** (lines 116, 131, 149, 195-196):
- `subscription.listener.error_handler` → `subscription.listener.invoker.error_handler`

**tests/unit/bus/test_bus.py** (lines 88, 103, 147-148, 199-200, 212, 225, 240-241):
- `sub.listener.name` → `sub.listener.identity.name`
- `sub.listener.app_key` → `sub.listener.identity.app_key`
- `sub.listener.source_tier` → `sub.listener.identity.source_tier`
- `sub.listener.instance_index` → `sub.listener.identity.instance_index`

**tests/unit/bus/test_bus_timeout_threading.py** (lines 36, 42, 48-49, 57, 63):
- `sub.listener.timeout` → `sub.listener.options.timeout`
- `sub.listener.timeout_disabled` → `sub.listener.options.timeout_disabled`

**tests/unit/test_source_tier_propagation.py** (lines 98, 103, 108):
- `sub.listener.source_tier` → `sub.listener.identity.source_tier`

**tests/unit/core/test_command_executor.py** (line 21):
- `cmd.listener.invoke` → `cmd.listener.invoker.invoke`

**tests/integration/test_bus.py** (lines 927-928, 938-939, 962-963, 973-974):
- `subscription.listener.immediate` → `subscription.listener.duration_config.immediate`
- `subscription.listener.entity_id` → `subscription.listener.duration_config.entity_id`
- `subscription.listener.duration` → `subscription.listener.duration_config.duration`

**tests/integration/test_bus_duration.py** (line 379):
- `sub.listener.duration` → `sub.listener.duration_config.duration`
- `sub.listener.entity_id` → `sub.listener.duration_config.entity_id`

**tests/system/conftest.py** (line 264) and **tests/system/test_bus.py** (lines 53, 85, 222):
- `sub.listener.db_id` stays as-is (db_id remains on Listener)

**Step 2: Verify Listener.create() backward compat.** Run the full test suite to confirm all 57 existing test kwargs call sites (and 5 production call sites) work without modification. The factory constructs sub-structs internally from kwargs.

**Step 3: Fix lazy imports** in `src/hassette/event_handling/accessors.py`:
- Move `from hassette.events import RawStateChangeEvent` (line 221) to module top level
- Move `from hassette.events import CallServiceEvent` (line 239) to module top level
- Combine into a single import: `from hassette.events import CallServiceEvent, RawStateChangeEvent`
- No circular import exists (verified in research)

**Step 4: Remove backward-compat shims** from `src/hassette/bus/listeners.py`:
- Delete all `@property` accessors added in T01 Step 2b (the block marked as temporary backward-compat shims)
- Delete all method forwards (`dispatch()`, `invoke()`, `mark_fired()`, `set_app_error_handler_resolver()` on Listener)
- After this step, the only way to access sub-struct fields is through the sub-struct: `listener.identity.app_key`, `listener.invoker.dispatch()`, etc.
- Run `grep -n "def \(dispatch\|invoke\|mark_fired\|set_app_error\)" src/hassette/bus/listeners.py` to confirm only HandlerInvoker owns these methods

**Step 5: Run the full test suite** via `timeout 300 uv run nox -s dev -- -n 2` to confirm zero regressions.

## Focus
- The ~32 field-access updates are strictly mechanical — `listener.X` becomes `listener.sub_struct.X`. No test logic, assertions, or setup changes.
- `db_id` stays on Listener directly (not in any sub-struct) — test_bus.py lines referencing `sub.listener.db_id` do NOT need updating.
- `listener.listener_id` stays on Listener — any test referencing it does NOT need updating.
- `listener.topic` and `listener.predicate` stay on Listener — no updates needed.
- For duration_config fields: tests accessing `sub.listener.duration` etc. where the listener was NOT created with `duration=` will need careful handling — if `duration_config` is None, these would fail. Check each test to confirm the listener was created with duration options.
- The lazy import fix in accessors.py is isolated and safe — the research brief confirmed no circular dependency.
- The backward-compat properties added in T01 are removed HERE, not in T01 — they exist only to keep T02/T03 passing before T04/T05 migrate consumers. After Steps 1-3 complete, all consumers use sub-struct paths and the properties are dead code. Remove the entire shim block.

## Verify
- [ ] FR#6: All 57 test and 5 production Listener.create() kwargs call sites work without modification (run test suite)
- [ ] FR#12: `src/hassette/event_handling/accessors.py` has no function-body imports — only top-level imports
- [ ] AC#3: Full test suite passes with only field-access path changes (no test logic modifications)
- [ ] AC#12: grep -n "from hassette" accessors.py shows all imports at file top level, none inside function bodies

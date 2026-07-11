---
task_id: "T03"
title: "Migrate test_fatal_shutdown.py to public properties"
status: "done"
depends_on: ["T01"]
implements: ["FR#5", "FR#8", "AC#1", "AC#4"]
---

## Summary
Migrate all private-attribute service access in `tests/integration/test_fatal_shutdown.py` to use public properties. Annotate remaining state-machine test sites (SessionManager internals, `_fatal_shutdown_reason` writes) with `# coordinator-internal`.

## Target Files
- modify: `tests/integration/test_fatal_shutdown.py`

## Prompt
In `tests/integration/test_fatal_shutdown.py`, perform these changes:

### 1. Replace private-attr reads with public properties

For every `hassette_instance._<service>` access, replace with the public property:
- `._database_service` → `.database_service`
- `._session_manager` → `.session_manager` (new property from T01)

### 2. Handle `_fatal_shutdown_reason` reads vs writes

- Reads (e.g., `assert hassette_instance._fatal_shutdown_reason is None`): Replace with `hassette_instance.fatal_shutdown_reason`
- Writes that set a reason (lines 41, 136, 162 — e.g., `hassette_instance._fatal_shutdown_reason = "BusService crashed"`): Replace with `hassette_instance.record_fatal_reason("BusService crashed")` — this public method (`core.py:664`) has "first reason wins" semantics matching these test setups exactly
- The one reset site (line 187, `hassette_instance._fatal_shutdown_reason = None`): Keep private access with `# coordinator-internal` annotation — no public method exists for resetting

### 3. Annotate SessionManager internal accesses

In `test_finalize_writes_failure_when_fatal_reason_set` (line ~157) and `test_finalize_writes_success_when_no_fatal_reason` (line ~182):
- `sm = hassette_instance._session_manager` → `sm = hassette_instance.session_manager` (use new public property)
- `sm._session_id`, `sm._session_error`, `sm._database_service` accesses: Keep private access with `# coordinator-internal` annotation

### 4. Handle `children` iteration

Tests iterate `hassette_instance.children` and compare with `hassette_instance._database_service` — replace the comparison side with `.database_service`:
```python
# Before
for child in hassette_instance.children:
    if child is not hassette_instance._database_service:

# After
for child in hassette_instance.children:
    if child is not hassette_instance.database_service:
```

## Focus
- `test_fatal_shutdown.py` has 7 tests, all in a `TestRunForeverFatalShutdown` class.
- The heaviest private-attr usage is `_session_manager` (mocking `mark_orphaned_sessions`, `create_session`, `cleanup_stale_once_listeners`, `finalize_session`).
- `_fatal_shutdown_reason` has ~4 writes (setup) and ~4 reads (assertions). Reads use the public `fatal_shutdown_reason` property. 3 writes use the public `record_fatal_reason()` method. Only the `= None` reset (line 187) stays private.
- Mock assignments to public methods (e.g., `hassette_instance.shutdown = AsyncMock()`) are standard test practice — these are not private-attr access.

## Verify
- [ ] FR#5: All service reads in test_fatal_shutdown.py use public properties
- [ ] FR#8: All remaining private-attr accesses have `# coordinator-internal` annotation
- [ ] AC#1: Zero `hassette_instance._<service>` access for services with public properties
- [ ] AC#4: All remaining private-attr sites annotated

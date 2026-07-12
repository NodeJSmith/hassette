---
task_id: "T02"
title: "Rename event factory classmethods to descriptive from_* names"
status: "done"
depends_on: []
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "AC#2"]
---

## Summary
Standardize the five event factory classmethods in `src/hassette/events/hassette.py` on a descriptive `from_*` naming family. Rename `from_data` to `from_service_status`/`from_app` and `create_event` to `from_topic`/`from_paths`. `from_record` stays unchanged. Update all 16 call sites in src/ and 11 in tests/.

## Target Files
- modify: `src/hassette/events/hassette.py`
- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/core/file_watcher.py`
- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/core/websocket_service.py`
- modify: `src/hassette/test_utils/helpers.py`
- modify: `src/hassette/test_utils/simulation.py`
- modify: `tests/unit/events/test_hassette_payload.py`
- modify: `tests/unit/events/test_service_status_payload.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/unit/bus/test_bus_registration_edge_cases.py`
- modify: `tests/unit/test_app_key.py`
- read: `design/specs/008-standardize-naming-v1/design.md`
- read: `design/specs/008-standardize-naming-v1/tasks/context.md`

## Prompt
Rename four event factory classmethods and update all call sites.

**Step 1: Rename methods in `src/hassette/events/hassette.py`**

| Class | Old method | New method |
|---|---|---|
| `HassetteServiceEvent` | `from_data` | `from_service_status` |
| `HassetteAppStateEvent` | `from_data` | `from_app` |
| `HassetteSimpleEvent` | `create_event` | `from_topic` |
| `HassetteFileWatcherEvent` | `create_event` | `from_paths` |

Do NOT rename `HassetteExecutionCompletedEvent.from_record` — it stays as-is.

**Step 2: Update all src/ call sites (16 total)**

`HassetteServiceEvent.from_data` → `.from_service_status` (4 calls):
- `src/hassette/resources/mixins.py:355`
- `src/hassette/test_utils/simulation.py:280`
- `src/hassette/test_utils/helpers.py:427`
- `src/hassette/test_utils/helpers.py:437`

`HassetteAppStateEvent.from_data` → `.from_app` (4 calls):
- `src/hassette/test_utils/simulation.py:444`
- `src/hassette/core/app_lifecycle_service.py:261`
- `src/hassette/core/app_lifecycle_service.py:282`
- `src/hassette/core/app_lifecycle_service.py:346`

`HassetteSimpleEvent.create_event` → `.from_topic` (6 calls):
- `src/hassette/test_utils/simulation.py:382`
- `src/hassette/test_utils/simulation.py:406`
- `src/hassette/core/websocket_service.py:736`
- `src/hassette/core/websocket_service.py:742`
- `src/hassette/core/app_lifecycle_service.py:312`
- `src/hassette/core/app_lifecycle_service.py:482`

`HassetteFileWatcherEvent.create_event` → `.from_paths` (2 calls):
- `src/hassette/test_utils/helpers.py:418`
- `src/hassette/core/file_watcher.py:61`

**Step 3: Update all test call sites (11 total)**

`HassetteServiceEvent.from_data` → `.from_service_status`:
- `tests/unit/events/test_hassette_payload.py:42`
- `tests/unit/events/test_service_status_payload.py:38, 50`
- `tests/unit/core/test_runtime_query_service.py:357, 375`

`HassetteAppStateEvent.from_data` → `.from_app`:
- `tests/unit/test_app_key.py:61, 62`
- `tests/unit/bus/test_bus_registration_edge_cases.py:197, 198`

`HassetteSimpleEvent.create_event` → `.from_topic`:
- `tests/unit/events/test_hassette_payload.py:51`

`HassetteFileWatcherEvent.create_event` → `.from_paths`:
- `tests/unit/events/test_hassette_payload.py:56`

**Step 4: Verify no stale references remain**
```bash
grep -rn '\.create_event(\|\.from_data(' src/hassette/events/ src/hassette/resources/ src/hassette/core/ src/hassette/test_utils/ tests/ --include="*.py"
```
This should return zero matches.

## Focus
- `src/hassette/core/command_executor.py:956` calls `HassetteExecutionCompletedEvent.from_record()` — this is NOT being renamed. Do not touch this file.
- `simulation.py` has 4 call sites (lines 280, 382, 406, 444), not 3 — don't miss line 444 (`HassetteAppStateEvent.from_data`).
- The renames are method-name-only. Signatures, parameters, and return types stay identical.
- Line numbers are approximate — read each file and find the actual call sites by method name.

## Verify
- [ ] FR#3: `HassetteServiceEvent` has `from_service_status` classmethod, no `from_data`
- [ ] FR#4: `HassetteAppStateEvent` has `from_app` classmethod, no `from_data`
- [ ] FR#5: `HassetteSimpleEvent` has `from_topic` classmethod, no `create_event`
- [ ] FR#6: `HassetteFileWatcherEvent` has `from_paths` classmethod, no `create_event`
- [ ] FR#7: `HassetteExecutionCompletedEvent.from_record` is unchanged
- [ ] AC#2: `grep -rn '\.create_event(\|\.from_data(' src/hassette/events/ src/hassette/resources/ src/hassette/core/ src/hassette/test_utils/ tests/` returns no matches

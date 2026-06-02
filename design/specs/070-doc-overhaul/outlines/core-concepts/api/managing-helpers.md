# API — Managing Helpers

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Create and manage HA helpers (input_boolean, input_number, counter, timer, etc.) from their app, typically during startup to self-provision persistent entities.

## What was cut (and where it goes)

- **Typed Models section (the table of Record/Create/Update params)** — demoted to a collapsible section. Most readers want to create a helper, not understand the Pydantic model hierarchy. The model details matter when debugging serialization or understanding `exclude_unset` behavior, so they stay on the page but below the fold.
- **Per-domain method lists** (create_input_boolean, create_input_number, etc.) — the old outline listed each CRUD verb as its own H2, which mirrors the source code, not the reader's task. Consolidated into one section showing the pattern with one domain, then a reference table of all 8 domains.
- **Testing with the Harness** — kept but moved toward the end. Readers land here to create helpers, not to test them. Testing is the second job.

## Outline

### H2: (Opening — no heading)
HA helpers (`input_boolean`, `input_number`, `counter`, `timer`, etc.) are persistent entities stored in HA's `.storage/`. Apps create and manage them through typed `Api` methods — 32 CRUD methods across 8 domains, plus 3 counter shortcuts.

### H2: Creating a Helper on Startup
The most common pattern: create-if-not-exists in `on_initialize`. Show the idempotent bootstrap pattern (list, check, create) as the primary example. This is the snippet most readers will copy.

Snippet: bootstrap pattern from `crud_operations.py:bootstrap`.

Warning callout: concurrent provisioning and HA's silent auto-suffix behavior. Mitigation is naming discipline (prefix with app name), not retry logic.

### H2: CRUD Operations
Show create, list, update, delete using one domain (`input_boolean`) as the example. The pattern is identical across all 8 domains.

#### H3: Create
Snippet: `create_input_boolean(CreateInputBooleanParams(...))`.

#### H3: List
Snippet: `list_input_booleans()`.

#### H3: Update
`update_*` takes a `helper_id` (the stored id, not the display name) and a partial params object. Only fields passed are sent to HA.

#### H3: Delete
Returns `None`. Raises `FailedMessageError(code="not_found")` if the id is absent.

#### H3: All Supported Domains
Reference table: 8 domains (input_boolean, input_number, input_text, input_select, input_datetime, input_button, counter, timer) with their create/list/update/delete method names.

### H2: Counter Shortcuts
`increment_counter`, `decrement_counter`, `reset_counter` operate on the live entity state (not stored config). They take effect immediately.

Note: timer actions (`timer.start`, `timer.pause`, `timer.cancel`) are not wrapped — call them via `call_service` directly. The asymmetry is intentional: counter operations are high-frequency; timer actions are one-off.

### H2: Testing
`AppTestHarness.seed_helper(record)` pre-populates the harness store. Domain is derived from the record class.

Snippet: harness test example.

### H2: Gotchas
??? collapsible. Consolidated list:
- HA auto-suffixes on name collision (no error, silent `_2` suffix)
- `CreateInputDatetimeParams` requires `has_date=True` or `has_time=True`
- `exclude_unset=True` vs explicit `None` — omitting a field vs passing `None` produce different wire payloads
- `CounterRecord` vs `CounterState` — config vs runtime
- Helper creation persists across HA restarts
- `RetryableConnectionClosedError` as a second exception class

??? collapsible: Typed Models detail (Record/CreateParams/UpdateParams table with extra policies).

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `create_helper.py` | Move to `api/snippets/` | Single create example |
| `crud_operations.py` | Move to `api/snippets/` | List/update/delete/bootstrap |
| `counter_shortcuts.py` | Move to `api/snippets/` | Counter operations |
| `testing_harness.py` | Move to `api/snippets/` | Harness seed example |
| `timer_call_service.py` | Move to `api/snippets/` | Timer via call_service |

## Cross-Links

- **Links to:** API overview, Services (call_service for timer actions), Testing (harness), Apps lifecycle (bootstrap in on_initialize)
- **Linked from:** API overview

# API — Managing Helpers

**Status:** Stub (3 lines), content moving from Advanced (168 lines)
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

Content source: `docs/pages/advanced/managing-helpers.md`

### H2: Typed Models
HA helper types (InputBoolean, InputNumber, etc.) as typed Pydantic models.

### H2: Creating a Helper
Per-type methods: `create_input_boolean()`, `create_input_number()`, etc.

### H2: Listing Helpers
Per-type methods: `list_input_booleans()`, `list_input_numbers()`, `list_counters()`, `list_timers()`, etc.

### H2: Updating a Helper
Per-type methods: `update_input_boolean()`, `update_input_number()`, etc.

### H2: Deleting a Helper
Per-type methods: `delete_input_boolean()`, `delete_input_number()`, etc.

### H2: Idempotent Bootstrap (The Simple Pattern)
Create-if-not-exists pattern for app initialization.

### H2: Counter Service-Call Shortcuts
`increment_counter()`, `decrement_counter()`, `reset_counter()` for counter helpers.

### H2: Testing with the Harness
How `RecordingApi` handles helper operations in tests.

### H2: Gotchas
Known limitations and edge cases (HA API quirks).

## Snippet Inventory

Moving from `advanced/snippets/managing-helpers/` (5 files):
| Snippet | Status | Notes |
|---|---|---|
| `create_helper.py` | Move | → `api/snippets/` |
| `crud_operations.py` | Move | |
| `counter_shortcuts.py` | Move | |
| `testing_harness.py` | Move | |
| `timer_call_service.py` | Move | |

## Cross-Links

- **Links to:** API overview, Testing (harness), Apps lifecycle (bootstrap in on_initialize)
- **Linked from:** API overview

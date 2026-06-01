# Testing — Factories & Internals

**Status:** Exists (169 lines), reference-style, voice polish needed
**Voice mode:** Reference — terse, system-as-subject

## Outline

### H2: Event Factories
#### H3: `create_state_change_event` — build a state change event dict
#### H3: `make_full_state_change_event` — build from pre-made state dicts
#### H3: `create_call_service_event` — build a service call event dict
#### H3: `create_component_loaded_event`, `create_service_registered_event`

### H2: State Factories
#### H3: `make_state_dict` — raw state dict
#### H3: `make_light_state_dict` — typed light state
#### H3: `make_sensor_state_dict` — typed sensor state
#### H3: `make_switch_state_dict` — typed switch state

### H2: `make_mock_hassette`
Full mock Hassette instance for unit tests.

### H2: `create_hassette_stub`
Web-layer stub that wires a full FastAPI app stack — for testing web routes and WebSocket endpoints. Not an alias for `make_mock_hassette`. Internal helper (not in `__all__`), imported from `hassette.test_utils._internal`.

### H2: `make_test_config`
Test configuration builder.

### H2: RecordingApi Coverage Boundary
What RecordingApi supports vs what needs mocking.

### H2: Internal Helpers
Functions available from `hassette.test_utils._internal` (not in `__all__` — stable but not part of the public API contract). Includes `create_hassette_stub`, `create_component_loaded_event`, `create_service_registered_event`, `make_full_state_change_event`. Document what they do so users of the web layer can find them, but note the internal status.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `testing/snippets/` | Review | Factory usage examples |

## Cross-Links

- **Links to:** Testing overview, API overview (RecordingApi boundary)
- **Linked from:** Testing overview

# Testing — Factories & Internals

**Status:** Exists (169 lines), reference-style, voice polish needed
**Voice mode:** Reference — terse, system-as-subject

## Outline

### H2: Event Factories
#### H3: `create_state_change_event` — build a state change event dict
#### H3: `create_call_service_event` — build a service call event dict

### H2: State Factories
#### H3: `make_state_dict` — raw state dict
#### H3: `make_light_state_dict` — typed light state
#### H3: `make_sensor_state_dict` — typed sensor state
#### H3: `make_switch_state_dict` — typed switch state

### H2: `make_mock_hassette`
Full mock Hassette instance for unit tests.

### H2: `create_hassette_stub`
Separate Tier 2 web-specific stub for HTTP/WebSocket tests. Not an alias for `make_mock_hassette`.

### H2: `make_test_config`
Test configuration builder.

### H2: RecordingApi Coverage Boundary
What RecordingApi supports vs what needs mocking.

### H2: Tier 2 Re-exports
Helper re-exports from `hassette.test_utils`.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `testing/snippets/` | Review | Factory usage examples |

## Cross-Links

- **Links to:** Testing overview, API overview (RecordingApi boundary)
- **Linked from:** Testing overview

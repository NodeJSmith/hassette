# API — Services

**Status:** Exists (35 lines), brief, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Basic Service Calls
`call_service(domain, service, target=None, return_response=False, **data)` — service data is passed as `**kwargs`, NOT a positional dict. `target` is a separate parameter for entity targeting.

### H2: Convenience Helpers
`turn_on`, `turn_off`, `toggle_service` — all default to `domain="homeassistant"` (the deprecated generic HA service). Docs should warn to pass the correct domain (e.g., `domain="light"`).

### H2: Service Responses
`return_response=True` changes return type from `None` to `ServiceResponse`. This is opt-in.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `api/snippets/` | Review | Service call examples |

## Cross-Links

- **Links to:** API overview, Bus handlers (on_call_service for reacting to service calls)
- **Linked from:** API overview, Recipes

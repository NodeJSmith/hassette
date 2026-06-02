# Recipes — React to a Service Call

**Status:** Exists (32 lines), follows recipe template, voice polish needed
**Voice mode:** Recipe — problem statement, code, How It Works, variations

## Outline

### H2: (Problem Statement)
React when a specific HA service is called (e.g., log when someone turns on a light via the UI).

### H2: The Code
App with `on_call_service` subscription.

### H2: How It Works
Service call events, filtering by domain/service.

### H2: Verify It's Working
`hassette listener --app <key>` to confirm the service-call handler is registered. Trigger the service via HA UI, then `hassette log --app <key> --since 5m` to see the handler fire. Expected: one log entry per service call matching the filter.

### H2: Variations
Filtering by entity, combining with state checks.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `service_call_reaction.py` (in `recipes/snippets/`) | Keep | Review for voice |

## Cross-Links

- **Links to:** Bus/Handlers (on_call_service), Bus/Filtering (service call filtering), Testing overview (write a test for this pattern)
- **Linked from:** Recipes overview

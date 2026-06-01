# API — Overview

**Status:** Exists (70 lines), concise, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: (Opening)
What the API handle provides: async interface to HA REST and WebSocket APIs. Available as `self.api` on every app.

### H2: Usage
Basic `call_service`, `get_state`, `get_states` patterns.

### H2: Error Handling
What happens when HA is unreachable, timeouts, error responses.

### H2: Synchronous Usage
`self.api.sync` for sync contexts (rare).

### H2: API vs StateManager
When to use `self.api.get_state()` vs `self.states.get()`. API = fresh from HA; StateManager = cached local state.

### H2: Next Steps
→ Entities & States, → Services, → Managing Helpers, → Utilities

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Files from `api/snippets/` (14 total) | Review | Assign per-page |

## Cross-Links

- **Links to:** Entities, Services, Managing Helpers, Utilities, States overview
- **Linked from:** Architecture, Apps overview

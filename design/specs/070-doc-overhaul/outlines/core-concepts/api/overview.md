# API Overview

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Understand what `self.api` is, when to use it vs `self.states`, and find the right subpage for their specific task.

## What was cut (and where it goes)

- **Detailed error handling** — the existing page lists three exception types and says "network errors are automatically retried." That is the right level for an overview. No change needed.
- **Synchronous usage** — kept but demoted to a collapsible section. Most readers use async; sync is a special case that shouldn't occupy equal visual weight on the landing page.

## Outline

### H2: (Opening — no heading)
One-sentence definition: `self.api` is the async interface to Home Assistant's REST and WebSocket APIs. Available on every app. Handles auth, retries, and type conversion.

Mermaid diagram showing App -> Api -> HA (keep existing diagram, it earns its space).

### H2: Quick Example
Minimal snippet showing the two most common operations: reading state and calling a service. This answers "what does using it look like?" before anything else.

### H2: API vs StateManager
This is the first decision the reader faces: should I even be on this page? Lead with the answer: prefer `self.states` for reading state (cached, sync, fast). Use `self.api` when fresh-from-HA data is needed, or for writes (service calls, set_state, helpers).

Short table: StateManager vs API — access pattern, latency, use case.

### H2: Error Handling
Three exception types. Network errors retried automatically. Catch `HassetteError` as the base.

### H2: Synchronous Usage
??? collapsible. `self.api.sync` for `AppSync` contexts. Warning about deadlock if called from event loop.

### H2: Next Steps
Links to subpages, ordered by frequency of use:
- Entities & States (reading data)
- Services (calling services)
- Managing Helpers (CRUD for input_boolean, counters, etc.)
- Utilities (history, templates, calendars)

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `api_overview_usage.py` | Keep | Core overview example |
| `api_sync_usage.py` | Keep | Sync usage collapsible |

## Cross-Links

- **Links to:** Entities & States, Services, Managing Helpers, Utilities, States overview
- **Linked from:** Architecture, Apps overview, Getting Started

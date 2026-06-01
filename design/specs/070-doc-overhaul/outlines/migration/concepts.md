# Migration — Mental Model

**Status:** Exists (90 lines), solid content, voice polish needed
**Voice mode:** Concept — comparison-driven, "you" allowed

## Outline

### H2: Execution Model
Single-threaded async (Hassette) vs multi-threaded (AppDaemon).

### H2: Access Model
Handles vs global `self.get_state()`.

### H2: Inheritance vs Composition
AppDaemon's Hass base class vs Hassette's App[Config] + handles.

### H2: Typed vs Untyped
String-based AppDaemon vs typed Pydantic models.

### H2: Callback Signatures
Raw dicts (AppDaemon) vs DI annotations (Hassette).

### H2: Synchronous API
`self.call_service()` (AppDaemon) vs `await self.api.call_service()` (Hassette).

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant comparison snippets from `migration/snippets/` | Review | Side-by-side examples |

## Cross-Links

- **Links to:** Migration overview, Apps overview
- **Linked from:** Migration overview

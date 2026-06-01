# Apps — Lifecycle

**Status:** Exists (80 lines), concise, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Initialization
`on_initialize` → `on_ready` sequence. What each hook is for. Registration happens in `on_initialize`; `on_ready` fires after all apps finish initializing.

### H2: Shutdown
`on_shutdown` hook. Cleanup order.

### H2: Automatic Cleanup
How Hassette cleans up bus subscriptions and scheduler jobs when an app shuts down.

### H2: AppSync Lifecycle Hooks
`on_apps_ready` and `on_apps_shutdown` for cross-app coordination.

## Snippet Inventory

Snippets from `apps/snippets/` that demonstrate lifecycle hooks — review and assign.

## Cross-Links

- **Links to:** Apps overview, Task Bucket, Bus overview (registration in on_initialize)
- **Linked from:** Apps overview (next steps)

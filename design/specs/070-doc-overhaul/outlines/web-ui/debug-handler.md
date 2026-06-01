# Web UI — Debug a Failing Handler

**Status:** Stub (3 lines), new task-oriented page
**Voice mode:** Getting-started feel — "you" allowed, procedural, task-focused

## Outline

Walks through using the Web UI to debug a handler that isn't firing or is throwing errors. Consolidates relevant content from old `handlers.md` and `app-detail/handlers.md`.

### H2: Symptoms
What "failing handler" looks like: handler never fires, fires but errors, fires too often.

### H2: Check the Handlers Page
Global handlers table. How to find your handler, read its status, see error counts. Consolidates from old `handlers.md`.

### H2: Drill into an App's Handlers
App detail → Handlers tab. Per-handler invocation history, error details. Consolidates from old `app-detail/handlers.md`.

### H2: Read the Invocation Logs
Execution ID filtering to trace a single invocation through the log stream.

### H2: Common Causes
Brief problem/solution list specific to handlers (missing `name=`, wrong entity pattern, DI annotation mismatch).

## Snippet Inventory

No code snippets — screenshots or UI descriptions.

## Cross-Links

- **Links to:** Web UI overview, Logs page, Bus/Handlers (handler mechanics), Bus/DI (annotation reference)
- **Linked from:** Web UI overview, Bus/Handlers (troubleshooting)

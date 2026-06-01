# Migration — Scheduler

**Status:** Exists (93 lines), comparison-driven, voice polish needed
**Voice mode:** Comparison — "you" allowed

## Outline

### H2: Overview
What changes: `run_in` stays, `run_daily` stays, `run_every` stays. Callback signature changes.

### H2: Callback Signatures
AppDaemon kwargs dict → Hassette typed params.

### H2: Method Equivalents
Table: AppDaemon method → Hassette method.

### H2: Side-by-Side Comparison
Full example: daily task in AppDaemon vs Hassette.

### H2: Migration Example
Complete before/after.

### H2: Blocking Work in Scheduler Callbacks
`run_in_executor` for blocking code.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~5 migration/scheduler snippets | Keep | Comparison pairs |

## Cross-Links

- **Links to:** Scheduler overview, Scheduler/Methods
- **Linked from:** Migration overview

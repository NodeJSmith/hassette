# Scheduler — Overview

**Status:** Exists (46 lines), brief intro, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: (Opening)
What the scheduler does: runs functions at specific times or intervals via trigger objects. Available as `self.scheduler` on every app.

### H2: Trigger Types
Table of built-in triggers (After, Once, Every, Daily, Cron) with one-line descriptions.

### H2: Examples
Minimal examples for the most common patterns (run_in, run_every, run_daily).

### H2: Job Groups
`group=` parameter for organizing related jobs. `cancel_group()` cancels all jobs in a group. `list_jobs(group=)` inspects active jobs. (Moved from Methods — this is a behavioral concept, not a method signature.)

### H2: Jitter
`jitter=` parameter for randomizing execution times to avoid thundering herd.

### H2: Idempotent Registration
`name=` identifies the job; `if_exists=` (`"error"`, `"skip"`, `"replace"`) controls behavior on duplicate name.

### H2: Next Steps
→ Scheduling Methods (full reference), → Job Management (cancellation, errors)

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `scheduler/snippets/` (22 total) | Review | Assign per-page |

## Cross-Links

- **Links to:** Scheduling Methods, Job Management, Apps overview
- **Linked from:** Architecture, First Automation, Recipes

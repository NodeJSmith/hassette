# Migration — Overview

**Status:** Exists (92 lines), solid content, voice polish needed
**Voice mode:** Getting-started — "you" allowed, comparison-driven

## Outline

### H2: Is Migration Worth It?
Honest assessment of when migration makes sense.

### H2: Known Gaps
What AppDaemon has that Hassette doesn't (yet).

### H2: What Changes
High-level summary of differences.

### H2: Quick Start Checklist
Abbreviated migration steps.

### H2: Guide Structure
How the migration section is organized.

### H2: Quick Reference Table
AppDaemon method → Hassette equivalent lookup table.

### H2: Common Pitfalls
(Moved from deleted checklist) Known gotchas:
- `name=` required on all bus subscriptions (`ListenerNameRequiredError`)
- `run_daily` signature differs from AppDaemon (takes `at="HH:MM"`, default `"00:00"`, DST-safe)
- Blocking code must use `task_bucket.run_in_thread()`, not `run_in_executor`
- `self.states.light.get()` is the idiomatic typed access, not `self.states.get()`

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `migration/snippets/` (27 total) | Review | Assign per-page |

## Writing Note

The existing AD migration docs already have AppDaemon-side code examples and side-by-side comparisons. Carry those forward — the AD parts should not be blank stubs. The current docs at `docs/pages/migration/` have these examples; reuse them.

Migration Checklist has been removed — it was a thin summary of the sub-pages with no unique content.

## Cross-Links

- **Links to:** All migration sub-pages, Is Hassette Right for You?
- **Linked from:** Home page, Is Hassette Right for You?

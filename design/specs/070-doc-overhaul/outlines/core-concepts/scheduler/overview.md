# Scheduler

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (landing page)
**Reader's job:** Schedule a function to run at a specific time or interval.

The existing page leads with trigger objects and the `schedule()` method — the framework author's mental model. The reader doesn't care about trigger internals. They want to run something after a delay, at a time, or on a schedule. Lead with the three most common patterns (`run_in`, `run_every`, `run_daily`) using code, then introduce the concept of triggers as the underlying mechanism for readers who need custom scheduling.

## What was cut (and where it goes)

- **Job groups, jitter, idempotent registration** — the previous outline had these as H2 sections here. These are operational concerns, not the reader's first job. They belong on the Methods page (groups, jitter, idempotent registration) or Management page (groups for cancellation). A brief mention in a "what else" list at the end is enough for the overview.
- **Trigger type table** — demoted from the lead position to a supporting section. The convenience methods are what readers actually use; triggers are the mechanism underneath.

## Outline

### H2: Common Patterns
Three snippets showing the most common scheduling tasks. No parameter tables, no trigger theory — just working code:
1. **Run after a delay** — `run_in(self.check_door, 300)` (5 minutes)
2. **Run on a repeating interval** — `run_every(self.poll_sensor, minutes=5)`
3. **Run daily at a fixed time** — `run_daily(self.morning_report, at="07:00")`

Each gets 1-2 sentences of explanation.

### H2: Trigger Types
All scheduling methods create a trigger object under the hood. For most cases, the convenience methods are sufficient. The `schedule()` method accepts a trigger directly for advanced use.

Table of built-in triggers: `After`, `Once`, `Every`, `Daily`, `Cron` — one-line descriptions, one-shot column.

### H2: Next Steps
- Scheduling Methods — full method reference, cron expressions, custom triggers, per-job options
- Job Management — cancelling, grouping, error handling, and the `ScheduledJob` object

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `scheduler_start_examples.py` | Keep | Opening examples (three common patterns) |

No new snippets needed.

## Cross-Links

- **Links to:** Scheduling Methods, Job Management, Apps overview
- **Linked from:** Architecture, First Automation, Recipes

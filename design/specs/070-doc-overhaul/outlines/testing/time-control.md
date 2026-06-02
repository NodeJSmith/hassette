# Testing — Time Control

**Status:** Exists (48 lines), mostly GENUINE — good structure, needs JTBD metadata
**Voice mode:** Concept — system-as-subject
**Page type:** Depth page (concept + reference)
**Reader's job:** Test scheduler-driven behavior by freezing and advancing time deterministically.

## What was cut

Nothing. The existing page is well-structured: opens with the canonical
sequence (the pattern readers will copy), then covers each method with a
focused explanation and example. The `advance_time` warning about needing
`trigger_due_jobs` is exactly the kind of trap that earns its admonition.

The `whenever` note stays — readers will wonder where `Instant` comes from.

## Outline

### Opening line
One sentence: test scheduler-driven behavior by freezing time and advancing it
manually.

### Canonical sequence
Complete example showing the freeze-advance-trigger pattern. This is the most
important content — readers copy this first.

### H2: freeze_time(instant)
Freezes `now` at the given time. Accepts `Instant` or `ZonedDateTime` from
`whenever`. Idempotent — calling again replaces the frozen time. Auto-unfrozen
on `async with` exit.

### H2: advance_time
Advances the frozen clock by a delta. Warning: does not trigger jobs by itself.
Must call `trigger_due_jobs()` after.

### H2: trigger_due_jobs
Fires all jobs due at or before the current frozen time. Returns job count.
Re-enqueued repeating jobs are not re-triggered in the same call.

### H2: Next Steps
Links to Concurrency (time lock interaction with xdist), Testing index.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `testing_time_control_sequence.py` | Keep | Canonical sequence |
| `testing_freeze_time.py` | Keep | freeze_time example |
| `testing_advance_time.py` | Keep | advance_time example |
| `testing_trigger_due_jobs.py` | Keep | trigger_due_jobs example |

## Cross-Links

- **Links to:** Concurrency (time lock), Testing index, Scheduler/Methods (trigger types)
- **Linked from:** Test Harness Reference (next steps)

# Recipes — Motion-Activated Lights

**Status:** REWRITTEN in T03 (exemplar). 62 lines. GENUINE — keep as-is.
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Build a motion-activated light automation that turns on instantly and turns off after a configurable delay with re-trigger support.

## What was cut

Nothing. This page was the exemplar for the recipe template rewrite. It already
follows the correct pattern: problem statement, code, flowing prose "How It
Works" (no bullet lists with bold lead-ins), concrete verify step, variations.

## Outline

Already complete and well-structured. Covers:

### H2: (Problem statement)
Motion sensor scenario with re-trigger requirement.

### H2: The Code
Full app via `--8<--` include.

### H2: How It Works
Flowing prose paragraphs, system-as-subject. One decision per paragraph:
subscription strategy, on-handler cancel-then-act, off-handler run_in with
stored job, named job for deduplication, config-driven entity IDs.

### H2: Verify It's Working
Concrete commands: `hassette log --app motion_lights --since 5m` and
`hassette listener --app motion_lights`.

### H2: Variations
Config-only timeout change, split handlers with `changed_to` predicates.

### H2: See Also
Links to Bus, Scheduler, Application Configuration.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `motion_lights.py` | Keep | Main app, tested in T03 |
| `motion_lights_split.py` | Keep | Split handler variation, tested in T03 |

## Cross-Links

- **Links to:** Bus overview, Scheduler/Methods (run_in), Application Configuration, Testing overview
- **Linked from:** Recipes overview, First Automation (next steps)

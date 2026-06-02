# Recipes — Vacation Mode Toggle

**Status:** Exists (29 lines), needs JTBD redesign — "How It Works" uses bullet lists with bold lead-ins (anti-pattern)
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Toggle an automation's behavior on and off from the HA UI using an input_boolean, without redeploying or restarting Hassette.

## What was cut

The existing "How It Works" uses bold-label bullet lists. Content stays, format
changes to flowing prose paragraphs.

Missing a "Verify It's Working" section. Adding one.

## Outline

### H2: (Problem statement)
You're going on vacation and want your lights to simulate presence — random
toggles on a schedule. When you get back, flip a switch in HA to stop it. No
code changes, no restart.

### H2: The Code
Full app via `--8<--` include of `vacation_mode.py`.

### H2: How It Works
Flowing prose paragraphs, one decision each:

1. Two subscriptions — one fires when `input_boolean.vacation_mode` turns on,
   the other when it turns off. Each does exactly one thing.
2. Starting the loop — when vacation mode activates, `run_every` schedules
   `simulate_presence` on a fixed interval. The returned `ScheduledJob` is
   stored on the instance for later cancellation.
3. Presence simulation — each tick picks a random light and toggles it. On
   becomes off, off becomes on. The irregularity creates a lived-in pattern.
4. Stopping cleanly — when vacation mode deactivates, the stored job is
   cancelled and all lights are turned off to restore a known state.
5. Config — entity IDs and interval come from `VacationModeConfig`. Different
   houses get different light lists without code changes.

### H2: Verify It's Working
Toggle `input_boolean.vacation_mode` in the HA UI, then:
`hassette log --app <key> --since 5m` to see the mode-change handler fire and
the simulation start. `hassette listener --app <key>` to confirm both
subscriptions are registered.

### H2: Variations
- Provision the helper from code — `api.create_input_boolean` in
  `on_initialize`. Link to Managing Helpers.
- Schedule vacation windows — replace the manual toggle with `run_cron` for
  evening-only simulation. Link to Scheduler/Methods.

### H2: See Also
Links to Managing Helpers, Bus overview, States overview.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `vacation_mode.py` | Keep | Review for voice alignment |

## Cross-Links

- **Links to:** Managing Helpers (create_input_boolean), Bus overview (on_state_change), Scheduler/Methods (run_every, run_cron), States overview
- **Linked from:** Recipes overview

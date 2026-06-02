# Recipes — Vacation Mode Toggle

**Status:** Exists (29 lines), follows recipe template, voice polish needed
**Voice mode:** Recipe — problem statement, code, How It Works, variations

## Outline

### H2: (Problem Statement)
Toggle a set of automations on/off based on an input_boolean (vacation mode, guest mode, etc.).

### H2: The Code
App watching an input_boolean, enabling/disabling other behaviors.

### H2: How It Works
Pattern: input_boolean as a mode switch, conditional logic in handlers.

### H2: Verify It's Working
Toggle the input_boolean in HA UI, then `hassette log --app <key> --since 5m` to see the mode-change handler fire. `hassette listener --app <key>` to confirm the subscription is registered. Expected: handler fires on each toggle with the correct boolean state.

### H2: Variations
Multiple modes, time-based auto-toggle, notification on mode change.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `vacation_mode.py` (in `recipes/snippets/`) | Keep | Review for voice |

## Cross-Links

- **Links to:** States/Subscribing (input_boolean state changes), API/Services (call_service for toggling), Cache (persisting mode state), Testing overview (write a test for this pattern)
- **Linked from:** Recipes overview

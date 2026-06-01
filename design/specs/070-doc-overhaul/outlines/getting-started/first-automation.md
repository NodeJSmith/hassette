# First Automation

**Status:** Exists (115 lines), needs restructuring for DI-first
**Voice mode:** Getting-started — "you" allowed, code-first, each step produces visible progress

## Outline

### H2: What You'll Build / What You'll Learn
Bulleted list: typed configuration, subscribing to state changes with DI, scheduling a recurring job. Sets expectations before the reader invests time.

### H2: Step 1 — Understand the App Class
App[Config] generic, lifecycle hooks. Minimal — enough to read the next steps.

### H2: Step 2 — Add Typed Configuration
AppConfig subclass, SettingsConfigDict, hassette.toml mapping.

### H2: Step 3 — Subscribe to a State Change
**DI-first:** Show `D.StateNew[states.SunState]` as the primary and only pattern. Explain `D` and `states` imports. No raw event handler mention — that lives on the Bus handlers page.

Voice-guide rule #17: show code first, then explain. Rule #8: functional definitions for `D` and `states` on first use.

### H2: Step 4 — Schedule a Recurring Job
`self.scheduler.run_every()` with a simple heartbeat. Show the handler receiving no DI params (just `self`).

### H2: Step 5 — Run It
Full app file, `hassette run`, expected output.

### H2: What You Just Built
Recap: config, bus subscription with DI, scheduler. One paragraph.

### H2: Next Steps
→ Bus overview, → Recipes, → Docker (production)

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `first_automation_step1.py` | Keep | App class basics |
| `first_automation_step2.py` | Keep | Config class |
| `first_automation_step3.py` | Rewrite | DI-first: use `D.StateNew[states.SunState]` as primary pattern |
| `first_automation_step3_raw.py` | Unclaimed | No longer used here — candidate for Bus handlers page |
| `first_automation_step4.py` | Keep | Scheduler example |
| `typed_handler.py` | Unclaimed | Redundant if DI is the default from step 3 |

## Cross-Links

- **Links to:** Bus overview, DI page, Scheduler overview, Recipes
- **Linked from:** Quickstart (next steps), Evaluator

# Migration — Migration Checklist

**Status:** Exists (109 lines), step-by-step, voice polish needed
**Voice mode:** Procedural — "you" allowed, numbered steps

## Outline

### H2: Before You Start
Prerequisites: Hassette installed, HA token, project structure.

### H2: Step 1: Configuration
Convert appdaemon.yaml → hassette.toml.

### H2: Step 2: App Structure
Convert class, imports, initialization.

### H2: Step 3: Event Listeners
Convert listen_state/listen_event → on_state_change/on.

### H2: Step 4: Scheduler
Convert run_in/run_daily/run_every.

### H2: Step 5: API Calls
Convert get_state/call_service/set_state.

### H2: Step 6: Test
Write tests for the migrated app.

### H2: Step 7: Verify Live
Run against real HA and verify behavior.

### H2: Common Pitfalls
Known gotchas from the migration.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~2 migration/checklist snippets | Keep | Before/after snippets |

## Cross-Links

- **Links to:** All migration sub-pages, Testing overview
- **Linked from:** Migration overview

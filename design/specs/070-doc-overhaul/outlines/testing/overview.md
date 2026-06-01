# Testing — Testing Your Apps

**Status:** Exists (243 lines), comprehensive, voice polish needed
**Voice mode:** Concept/getting-started hybrid — "you" allowed for procedural parts

## Outline

### H2: Installation
pytest + hassette test extras.

### H2: Quick Start
Minimal test example with the harness.

### H2: The Test Harness
#### H3: Constructor — `AppTestHarness(AppClass, config)` parameters
#### H3: Properties — `harness.bus`, `harness.scheduler`, `harness.api_recorder` (not `harness.api`), etc.

### H2: State Seeding
`harness.set_state()`, `harness.set_states()` (bulk), `harness.seed_helper()` (helper config for CRUD tests).

### H2: Simulating Events
#### H3: State Changes
#### H3: Attribute Changes
#### H3: Service Call Events
#### H3: Timeouts and Slow Handlers
#### H3: Typed Dependency Injection in Handlers
#### H3: Hassette Service Events
Also note the full `simulate_*` surface: `simulate_component_loaded`, `simulate_service_registered`, `simulate_websocket_connected/disconnected`, `simulate_homeassistant_restart/start/stop`, `simulate_app_state_changed/running/stopping`.

### H2: Asserting API Calls
#### H3: `assert_called` — verify service calls were made
#### H3: `assert_called_partial` — subset match on kwargs
#### H3: `assert_called_exact` — exact kwargs match
#### H3: `assert_not_called`
#### H3: `assert_call_count`
#### H3: `get_calls`
#### H3: `reset`

### H2: Configuration Errors
Testing invalid config detection.

### H2: Harness Startup Failures
Testing apps that fail during initialization.

### H2: Next Steps
→ Time Control, → Concurrency, → Factories

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 34 files in `testing/snippets/` | Review | Assign per-page across the 4 testing pages |

## Cross-Links

- **Links to:** Time Control, Concurrency, Factories, Apps overview
- **Linked from:** Getting Started (next steps), Migration/Testing

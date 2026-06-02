# Testing — Test Harness Reference

**Status:** Exists (243 lines), needs JTBD redesign — currently structured as API surface tour, should be task-organized
**Voice mode:** Reference — system-as-subject, no "you"
**Page type:** Reference
**Reader's job:** Look up how to do a specific testing task: seed state, simulate an event, assert an API call, handle errors.

## What was cut (and where it goes)

The existing page is well-written but organized by API surface (constructor,
properties, state seeding, simulating, asserting). A reader who knows they want
to "test that my handler called turn_on" has to scan the whole page to find the
right section.

Restructured into task-oriented sections. The API surface is the same — the
grouping changes from "what the harness exposes" to "what the reader is trying
to do."

Installation and Quick Start content stays on the index page (quickstart.md
which is now `pages/testing/index.md`). This page is for readers who already
have a working test and need to do something specific.

The "Typed dependency injection in handlers" section is moved up to appear right
after state change simulation, since DI is the standard way to write handlers
and most readers need it immediately.

## Outline

### H2: Prerequisites
One line: `hassette[test]` extras required. Link to Testing index for setup.

### H2: Seeding State
`set_state()` for single entities, `set_states()` for bulk. Warning: does not
fire bus events — seed before simulating. Warning: calling `set_state()` after
`simulate_state_change()` silently overwrites.

### H2: Simulating Events
Opening line: all simulate methods wait for handlers to finish before returning.

#### H3: State Changes
`simulate_state_change()` — publishes through the bus, waits for handlers.
Show DI usage inline (D.StateNew) since it is the standard pattern.

#### H3: Attribute Changes
`simulate_attribute_change()` — changes one attribute, keeps state value.
Warning: can also fire state-change handlers when `changed=False`.

#### H3: Service Calls
`simulate_call_service()` — publishes a call_service event. Show DI usage
(D.Domain).

#### H3: Hassette Service Events
`simulate_hassette_service_status()` and convenience wrappers for testing
app responses to internal service lifecycle changes.

#### H3: Timeouts
Default 2-second timeout on all simulate methods. Override with `timeout=`.
Note about task chain draining and `DrainFailure` — link to Concurrency page.

### H2: Asserting API Calls
`harness.api_recorder` records every `self.api` call.

#### H3: assert_called
Partial match — additional kwargs in the recorded call are allowed.

#### H3: assert_not_called

#### H3: assert_call_count

#### H3: get_calls
Returns `ApiCall` records with `method`, `args`, `kwargs`.

#### H3: reset
Clears recorded calls for mid-test isolation.

Note: `turn_on`, `turn_off`, `toggle_service` record under their own names,
not `call_service`.

### H2: Testing Configuration Errors
`AppConfigurationError` during setup — the `async with` body never runs.
Attributes: `app_cls`, `original_error`.

### H2: Testing Startup Failures
`TimeoutError` from harness — distinct from `DrainTimeout`. Check logs for
the real cause (exception in `on_initialize`).

### H2: Harness Constructor and Properties
Quick-reference tables for constructor parameters and exposed properties.
This is lookup material, placed last because readers need it least often.

### H2: Next Steps
Links to Time Control, Concurrency, Factories.

## Snippet Inventory

All existing snippets in `testing/snippets/` that are currently included on
the existing `index.md` page stay assigned to this page. No new snippets needed.

| Snippet | Status | Notes |
|---|---|---|
| `testing_state_seeding.py` | Keep | State seeding example |
| `testing_simulate_state_change.py` | Keep | State change simulation |
| `testing_simulate_attribute_change.py` | Keep | Attribute change simulation |
| `testing_attribute_change_both_handlers.py` | Keep | Warning example |
| `testing_simulate_call_service.py` | Keep | Service call simulation |
| `testing_simulate_service_failure.py` | Keep | Service lifecycle events |
| `testing_simulate_timeout.py` | Keep | Timeout override |
| `testing_di_state_change.py` | Keep | DI with state changes |
| `testing_di_call_service.py` | Keep | DI with service calls |
| `testing_assert_called.py` | Keep | Assert called |
| `testing_assert_turn_on_off.py` | Keep | Convenience method note |
| `testing_assert_not_called.py` | Keep | Assert not called |
| `testing_assert_call_count.py` | Keep | Assert call count |
| `testing_get_calls.py` | Keep | Get calls |
| `testing_recorder_reset.py` | Keep | Reset recorder |
| `testing_app_configuration_error.py` | Keep | Config error testing |
| `testing_constructor.py` | Keep | Constructor reference |

## Cross-Links

- **Links to:** Testing index (quickstart), Time Control, Concurrency, Factories, Apps overview
- **Linked from:** Testing index, Recipes (see also), Migration/Testing

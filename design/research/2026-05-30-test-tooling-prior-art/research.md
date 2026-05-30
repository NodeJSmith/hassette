---
topic: "Test tooling HA automation frameworks expose to users"
date: 2026-05-30
status: Draft
---

# Prior Art: Test Tooling HA Automation Frameworks Expose to Users

## The Problem

Users who write automations on top of a framework (AppDaemon apps, NetDaemon apps,
HA custom integrations, Hassette apps) need to test that code without a live Home
Assistant. The framework either ships first-party test tooling or leaves users to
assemble their own. The question for Hassette: what categories of user-facing test
functionality exist in the wider ecosystem, and which does `hassette.test_utils`
not yet have?

## How We Do It Today

Hassette already ships a mature, documented Tier 1 test API: `AppTestHarness`
(real-component async context manager), `RecordingApi` (recording fake HA API with
`assert_called` / `assert_called_partial` / `assert_called_exact` / `assert_not_called`
/ `assert_call_count`), 18 `simulate_*` event methods with task-bucket draining,
`freeze_time` / `advance_time` / `trigger_due_jobs` time control (whenever-native, not
freezegun), `make_test_config` (validated config builder), and state/event factories.
Four docs pages, 37+ tested snippets, API reference on the allowlist. This is further
along than most of the field.

## Patterns Found

### Pattern 1: Inject a fake HA context / driver, introspect its mocks
**Used by**: appdaemon-testing (`hass_driver`), NetDaemon (mock `IHaContext` + Moq)
**How it works**: Replace the DI'd HA-access object with a mock; exercise the app; read
the mock's recorded interactions (`hass_driver.get_mock("turn_on")`, Moq `Verify`).
**Strengths**: Fast, no event loop, leverages existing mock libs.
**Weaknesses**: Asserts the app *tried* to call, not that anything happened; raw-mock
introspection leaks internals.
**Hassette status**: ✅ COVERED — `RecordingApi` is this, with a purpose-built assertion
surface that's more ergonomic than raw mock introspection.
**Example**: https://nickwhyte.com/appdaemon-testing/

### Pattern 2: Fluent state/assertion DSL (`given_that` / `assert_that` / `time_travel`)
**Used by**: Appdaemon-Test-Framework
**How it works**: `assert_that('light.living_room').was.turned_on(brightness=255)`,
`.was_not.turned_off()`, `given_that.state_of(...).is_set_to(...)`. Hides mocks behind a
domain language; negative assertions first-class; `mock_functions_are_cleared()` resets
between phases.
**Strengths**: Reads like behavior; negative + per-target assertions are first-class.
**Weaknesses**: Bespoke DSL to maintain; string-keyed entities lose type safety.
**Hassette status**: ⚠️ PARTIAL — Hassette has `assert_called`/`assert_not_called` but
only `assert_not_called(method)` globally, not "turn_off was NOT called for light.kitchen",
and no per-kwargs call count. No fluent layer (probably not wanted — type-safe kwargs are
arguably better than stringly-typed DSL).
**Example**: https://hellothisisflo.github.io/Appdaemon-Test-Framework/

### Pattern 3: Capture lists for service calls AND events
**Used by**: HA core (`async_mock_service`, `async_capture_events`)
**How it works**: Helper returns a plain mutable list that fills with `ServiceCall` /
`Event` objects as the test runs. Assertions are ordinary list checks.
**Strengths**: Dead simple, composes with everything (incl. snapshots).
**Weaknesses**: No fluent sugar; needs a registry/bus seam.
**Hassette status**: ⚠️ HALF — service-call capture is covered by `RecordingApi`. EVENT
capture is the gap: there's no clean way to assert which events an app *emitted onto the
Bus* (the `simulate_*` methods push events IN; nothing records what flowed out). `fire_event`
is recorded, but bus-level emissions aren't capturable.
**Example**: https://github.com/home-assistant/core/blob/dev/tests/common.py

### Pattern 4: Virtual/frozen time that runs due callbacks
**Used by**: HA core (`async_fire_time_changed` + freezegun), Appdaemon-Test-Framework
(`time_travel.fast_forward`), NetDaemon (`TestScheduler` / Rx virtual time)
**How it works**: Advance a controllable clock; due scheduler jobs fire deterministically
and instantly. HA's `async_fire_time_changed` advances the clock AND fires due jobs in one call.
**Strengths**: Deterministic, instant, no sleeps.
**Weaknesses**: Needs an injectable clock; freezegun has sharp edges (global datetime patch).
**Hassette status**: ✅ COVERED and arguably ahead — whenever-native `freeze_time`/
`advance_time`/`trigger_due_jobs` avoids freezegun's pitfalls. Minor ergonomic gap:
`advance_time` doesn't auto-fire due jobs (separate `trigger_due_jobs` call), unlike HA's
combined `async_fire_time_changed`.
**Example**: https://netdaemon.xyz/docs/developer/unit_test/

### Pattern 5: Re-export internal test helpers / promote harness to public + pytest plugin
**Used by**: pytest-homeassistant-custom-component
**How it works**: Republish the framework's own internal test helpers as a stable pytest
plugin (`hass`, `aioclient_mock`, `MockConfigEntry`), refreshed daily. Users get ready-made
fixtures, not hand-rolled setup.
**Strengths**: Zero divergence between internal and user testing; fixtures for free.
**Weaknesses**: Couples user tests to unstable internals; fixture-ordering gotchas leak.
**Hassette status**: ⚠️ PARTIAL — Hassette promoted the harness to a public Tier 1 API
(good, and its Tier1/Tier2 split deliberately AVOIDS the coupling anti-pattern). But it
ships NO pytest plugin / public fixtures — users get a context manager, not
`@pytest.fixture`-based ergonomics, and there's no entry point registering fixtures.
**Example**: https://github.com/MatthewFlamm/pytest-homeassistant-custom-component

### Pattern 6: Snapshot testing of state output (syrupy)
**Used by**: HA core + pytest-homeassistant-custom-component (`HomeAssistantSnapshotExtension`)
**How it works**: Capture full state/attributes; assert against a committed snapshot via
syrupy. Domain-aware serializer makes rich objects diff cleanly.
**Strengths**: Wide coverage with one assertion; low authoring cost.
**Weaknesses**: Snapshot churn / rubber-stamping; needs a domain-aware serializer.
**Hassette status**: ❌ MISSING — no syrupy integration, no state-object serializer. A
genuine category gap. Whether it's wanted is a judgment call.
**Example**: https://developers.home-assistant.io/docs/development_testing/

### Pattern 7: Validated config builders (MockConfigEntry)
**Used by**: HA core (`MockConfigEntry`), appdaemon-testing (`automation_fixture(App, args=)`)
**How it works**: Build the config object the framework would load, without real config
flow, so one app class can be tested across many configs.
**Strengths**: Parametrized multi-config testing; removes YAML/config-flow from the path.
**Weaknesses**: Hand-built config can diverge from the validated shape.
**Hassette status**: ✅ COVERED — `make_test_config` builds validated `HassetteConfig`;
`AppTestHarness` validates the app config dict into `AppConfig`. Pydantic validation is
not bypassed. Minor: no dedicated parametrized-multi-config ergonomic helper.
**Example**: https://github.com/home-assistant/core/blob/dev/tests/common.py

### Pattern 8: HTTP/network mocking at the client seam (aioclient_mock)
**Used by**: HA core + pytest-homeassistant-custom-component
**How it works**: Patch client acquisition so HTTP hits a mock session; pre-register
responses, assert on recorded requests.
**Strengths**: Deterministic offline testing of cloud-API integrations.
**Weaknesses**: Only works if the client is centralized/injectable.
**Hassette status**: ⚠️ PARTIAL — the harness mocks Hassette's OWN HA HTTP (SimpleTestServer
via `with_api_mock`). For a USER app's own outbound HTTP (to a cloud API), Hassette offers
nothing — but the right answer there is DI (user injects their own client), so this is low
priority / arguably out of scope.
**Example**: https://github.com/MatthewFlamm/pytest-homeassistant-custom-component

### Pattern 9: Setup-context to separate seeding from change events
**Used by**: appdaemon-testing (`with hass_driver.setup():`)
**How it works**: State writes inside `setup()` don't fire callbacks; writes outside do.
Models "world is in state X (no reaction), now Y changes (react)".
**Strengths**: Eliminates spurious-callback false positives; explicit arrange/act boundary.
**Weaknesses**: Extra machinery; easy to forget the context.
**Hassette status**: ✅ COVERED, arguably cleaner — `set_state`/`set_states` seed without
firing; `simulate_state_change` fires. Two methods instead of a context flag.
**Example**: https://github.com/nickw444/appdaemon-testing

## Anti-Patterns

- **No first-party harness → community fragmentation.** AppDaemon shipped none, producing
  two competing third-party libs plus forks. Hassette already avoids this.
  (https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html)
- **Coupling user tests to unstable internal test APIs.** pytest-homeassistant-custom-component
  re-exports `tests.common`, which HA doesn't treat as stable. Hassette's Tier1/Tier2 split is
  the deliberate fix — keep any new public surface in Tier 1.
  (https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
- **Asserting on mocks instead of outcomes.** Pure mock-introspection verifies the app
  *called* turn_on, not that anything happened. `RecordingApi` shares this; the
  real-component `HassetteHarness` path is the outcome-oriented complement.

## Emerging Trends

- **Snapshot testing as default for wide state coverage** — HA core moved heavily to syrupy
  with a domain-aware serializer. (https://developers.home-assistant.io/docs/development_testing/)
- **Virtual schedulers over frozen wall-clocks** — NetDaemon `TestScheduler`,
  Appdaemon `time_travel`. Hassette's whenever-native injectable approach already aligns.

## Relevance to Us

Hassette covers Patterns 1, 4, 7, 9 fully and is ahead on time control (whenever-native) and
on the public-surface anti-pattern (Tier1/Tier2). The real gaps, in priority order:

1. **Event capture/assertion on the Bus** (Pattern 3 event half) — no analog to
   `async_capture_events`. Users can't cleanly assert "my app emitted event X."
2. **Pytest plugin with public fixtures** (Pattern 5 fixture half) — users get a context
   manager but no ready-made `@pytest.fixture`s or plugin entry point.
3. **Per-kwargs negative + count assertions** (Pattern 2 substance, not the DSL) —
   `assert_not_called(method, **kwargs)` and call-count-by-kwargs. Matches an internal-audit gap.
4. **Snapshot testing support** (Pattern 6) — syrupy + a Hassette state serializer. Optional;
   a judgment call on whether it fits the project's taste.
5. **Test scaffold via `hassette init`** (NetDaemon template precedent) — generate a working
   test file so users start with a passing example.
6. **`advance_time` that optionally fires due jobs** (Pattern 4 ergonomics) — small combine
   to match HA's one-call `async_fire_time_changed`.
7. **Outbound HTTP mocking for user apps** (Pattern 8) — low priority; DI is the real answer.

Skip (already covered well): service-call capture, time control, validated config builder,
setup-vs-change separation, first-party harness, public Tier 1 surface, fluent DSL (type-safe
kwargs preferred over stringly-typed DSL).

## Recommendation

File issues for gaps 1–3 (clear wins, low taste-risk, two of them already echoed by the
internal audit). Treat 4 (snapshots) and 5 (init scaffold) as discuss-first — they're real
categories but depend on project taste. Gaps 6–7 are minor / low priority. Do NOT pursue a
fluent assertion DSL — Hassette's type-safe kwargs are the better call than stringly-typed
`assert_that('light.x')`.

## Sources

### Reference implementations
- https://github.com/nickw444/appdaemon-testing — `hass_driver` fixture + mock introspection
- https://github.com/FlorianKempenich/Appdaemon-Test-Framework — fluent given_that/assert_that/time_travel
- https://github.com/MatthewFlamm/pytest-homeassistant-custom-component — re-exports HA core test helpers
- https://github.com/home-assistant/core/blob/dev/tests/common.py — async_mock_service / async_capture_events / async_fire_time_changed
- https://github.com/eugeneniemand/netdaemon-app-template — test scaffold in project template [not directly retrievable]

### Blog posts & writeups
- https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_2/ — custom component unit testing + CI [403 on fetch]

### Documentation & standards
- https://developers.home-assistant.io/docs/development_testing/ — HA testing principles + syrupy
- https://netdaemon.xyz/docs/developer/unit_test/ — NetDaemon mock IHaContext + TestScheduler
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon ships no official harness

Note: these URLs were not live-verified; three pages returned 403/404 on direct fetch and are
flagged inline.

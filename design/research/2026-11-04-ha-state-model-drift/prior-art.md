---
topic: "Keeping typed HA state/attribute models correct against what HA publishes"
date: 2026-11-04
status: Draft
---

# Prior Art: Keeping typed HA state models correct

## The Problem

A typed model of a Home Assistant entity's attributes is a claim about what HA publishes, and HA has no schema for state attributes. When the claim is wrong, a typed client either crashes or degrades. Hassette's #3794 is the worked example. `TimerAttributes.last_transition` was typed as a datetime from its name, but HA publishes the event suffix (`"finished"`). Every transitioned timer then failed conversion and fell back to `BaseState`, with an ERROR log.

## How We Do It Today

- Models come from two places:
  - Codegen generates them from HA source for components whose entity base class uses `CACHED_PROPERTIES_WITH_ATTR_`.
  - Everything else, the helper domains included, is hand-written.
- `test_fixture_data_parses_as_registered_state_class` converts every state in `tests/data/events/state_change_events.jsonl`.
  - That file is a one-time Dec 2025 capture from HA's `demo` integration, with no regeneration script.
  - 22 of 62 registered domains have no sample, and the test skips them without failing.
  - An attribute that is null or missing in a sample is also unchecked. A never-run timer has `last_transition: null`.
- System tests already run a pinned real HA (`HA_VERSION` in `scripts/docker/.env`) in Docker on every CI push. The `ha-version-bump` skill moves the pin each month.

## Patterns Found

### Pattern 1: Untyped attributes (`dict[str, Any]`)
**Used by**: AppDaemon, pyscript, homeassistant-api, hass-client.
**How it works**: Only the envelope is typed. Attributes stay a dict, and nothing is claimed, so nothing drifts.
**Strengths**: Zero maintenance.
**Weaknesses**: It gives up the type safety that is hassette's point.
**Read**: AppDaemon `models/internal/state.py`, pyscript `state.py`, homeassistant-api `models/states.py`, hass-client `models.py`, all opened.

### Pattern 2: Generate from a live instance's observed values, widening on conflict
**Used by**: NetDaemon nd-codegen.
**How it works**:
- The generator unions the attributes it sees per domain across a live instance's states.
- It maps JSON kinds to coarse types (string, double, bool, object, list) and ignores nulls.
- It never promotes a string to a datetime.
- Results persist in `EntityMetaData.json` and merge across runs, so conditionally present attributes accumulate. A type conflict widens to `object`.

**Strengths**: Grounded in real values, and it cannot make the `last_transition` mistake.
**Weaknesses**:
- A domain absent from the user's instance gets no type.
- Drift is invisible until the user re-runs the generator.
- The types are shallow.
- A runtime mismatch most likely throws when `.Attributes` is accessed. That is inferred from System.Text.Json defaults and wasn't tested.

**Read**: `AttributeMetaDataGenerator.cs`, `EntityMetaDataMerger.cs`, `EntityState.cs`.

### Pattern 3: Hand-written types, pinned only by upstream value tests
**Used by**: HA core (attribute names as a StrEnum, values pinned by equality asserts per transition), the HA frontend (`TimerEntity.last_transition?: string`), and hassette today.
**How it works**: A human reads the integration source and writes the type. Nothing checks it across repos.
**Weaknesses**: The author's type guess is unchecked, which is exactly how #3794 happened.
**Read**: core `timer/const.py` and `tests/components/timer/test_init.py`; frontend `src/data/timer.ts`.

### Pattern 4: Validate against a live, pinned upstream, driving the states that matter
**Used by**: general API-client contract-testing practice (re-recorded cassettes, scheduled drift jobs). No HA-ecosystem project found doing it.
**How it works**:
- Run the real service at a pinned version.
- Drive the transitions that produce conditional fields.
- Validate the captured payloads through the client's models.

**Strengths**:
- Detects drift directly.
- Helper domains can be created on a real container, which `demo` can't provide.
- Core's tests list each transition's attributes, which tells you what to drive.

**Weaknesses**: It covers only what the driver triggers, and it checks shape, not meaning.
**Read**: a general blog article. The HA application is this brief's adaptation.

## Anti-Patterns

- **Typing an attribute from its name.** `last_transition` sounds like a timestamp and isn't one.
- **Treating `demo` as representative of a domain.** Conditionally absent attributes, and helper domains `demo` doesn't create, pass without being checked.
- **Fallback to untyped on a conversion failure.** No peer in this set does it. NetDaemon throws, and the untyped libraries never convert.

## Relevance to Us

Hassette already has the expensive part of Pattern 4, a pinned real HA in CI that is bumped monthly. What it lacks is a check that runs against that HA. Pattern 2's key lesson carries over even without codegen: ground types in observed values, and accumulate attributes that only show up in some states. Its weakness is the one hassette shares, since a domain or attribute absent from the instance goes unchecked. That makes "fail when a registered domain has no sample" the piece no peer has and hassette needs. No peer builds machinery for semantic attribute typing at all. Most avoid the problem by not typing attributes.

## Recommendation

Use the system-test HA as the source of truth: a live check that every entity there converts to its registered class with no fallback, plus helpers configured and driven through transitions so conditional attributes are populated. Pair it with a coverage gate that names every registered domain without a live sample, through an explicit allowlist. Refreshing the committed JSONL fixture is optional once the live check exists. Coverage was thin: no HA-ecosystem project validates attribute types against a live HA, so this design has no direct precedent.

## Sources

### Reference implementations
- https://github.com/net-daemon/netdaemon/blob/0bb2d9b028a8db59003b15d262cbd003e48342b8/src/HassModel/NetDaemon.HassModel.CodeGenerator/MetaData/EntityMetaData/AttributeMetaDataGenerator.cs — NetDaemon attribute type inference
- https://github.com/net-daemon/netdaemon/blob/0bb2d9b028a8db59003b15d262cbd003e48342b8/src/HassModel/NetDaemon.HassModel.CodeGenerator/MetaData/EntityMetaData/EntityMetaDataMerger.cs — NetDaemon metadata merge/persistence
- https://github.com/net-daemon/netdaemon/blob/0bb2d9b028a8db59003b15d262cbd003e48342b8/src/HassModel/NetDaemon.HassModel/Entities/EntityState.cs — NetDaemon runtime deserialization
- https://github.com/net-daemon/netdaemon/commit/e0bc4232b33e177fef8d8967212db242adba7896 — NetDaemon EnsureStringConverter
- https://github.com/home-assistant/core/blob/dev/tests/components/timer/test_init.py — HA core timer attribute pinning
- https://github.com/home-assistant/frontend/blob/93eb44b0412e67b4f913ee1dcd6361a4add6b569/src/data/timer.ts — HA frontend TimerEntity
- https://github.com/GrandMoff100/HomeAssistantAPI/blob/main/homeassistant_api/models/states.py — homeassistant-api
- https://github.com/music-assistant/python-hass-client/blob/main/hass_client/models.py — hass-client
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/models/internal/state.py — AppDaemon
- https://github.com/custom-components/pyscript/blob/master/custom_components/pyscript/state.py — pyscript

### Documentation & writeups
- https://github.com/net-daemon/docs/blob/master/docs/user/hass_model/hass_model_codegen.md — NetDaemon codegen docs
- https://github.com/home-assistant/developers.home-assistant/blob/master/docs/core/entity.md — HA entity docs
- https://reliability-flakiness-engineering.com/network-api-mocking-for-reliable-tests/record-and-replay-http-traffic/detecting-stale-recorded-fixtures-in-ci/ — detecting stale recorded fixtures in CI

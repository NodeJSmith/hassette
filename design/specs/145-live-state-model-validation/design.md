# Design: Validate state models against a live Home Assistant

**Date:** 2026-11-04
**Status:** built
**Mode:** sketch
**Prior art:** design/research/2026-11-04-ha-state-model-drift/prior-art.md

## Summary

#3794 shipped because a hand-declared attribute type was never checked against what HA publishes. Timer is a codegen `discovery = "manual"` domain, and its override TOML (`codegen/src/hassette_codegen/overrides/timer.toml`) declared `last_transition` as `ZonedDateTime | None`. HA actually publishes the transition event's suffix (`"finished"`). Every transitioned timer then failed `TimerState` conversion and fell back to `BaseState`. That fallback is by design in `StateRegistry.try_convert_state`, so no test failed. The fix is on branch `3794`. This change closes the gap that let it through.

There are three gaps:

- **No check against HA for hand-typed attributes.** About 110 attributes on 32 models are typed by hand: 11 manual-discovery override TOMLs and 21 models outside codegen. Nothing compares them with HA output.
- **The one conversion test checks a stale sample.** `tests/integration/test_models.py::test_fixture_data_parses_as_registered_state_class` converts states from `tests/data/events/state_change_events.jsonl`, a one-time Dec 2025 capture from HA's `demo` integration.
  - 22 of 62 registered domains have no sample in it, and the test skips them without failing.
- **Attributes absent from a sample go unchecked.** An attribute that is null or missing in every sample passes. A never-run timer has `last_transition: null`.

The change adds a system test (new file, `tests/system/test_state_models.py`) that runs against the pinned HA container the system tests already start (`tests/system/docker-compose.yml`, `HA_VERSION` in `scripts/docker/.env`):

- Every state the test observes in a registered domain must convert to its registered class with no fallback. That covers states seen during the drive plus a final snapshot (D1). Conversion uses the resolved class directly, not `try_convert_state`'s fallback path, so a failure raises and names the entity and the validation error.
- `tests/fixtures/ha-config/configuration.yaml` gains entities for every registered domain the build can provide there. The target is every domain the JSONL capture samples, plus the helper and YAML-only domains named in D3. Anything the build can't provide goes on the domain allowlist. The test drives entities through the transitions that populate their conditional attributes.
  - The drive uses service calls only (`timer.start`, `timer.pause`, `timer.finish`, `timer.cancel`, and the equivalents for the other helpers). It never waits out a real duration.
  - After each call, the test waits with a timeout for the resulting state to appear among the observed states. A timeout fails the test, naming the entity and the expected state.
  - `timer.finish` is issued on an active timer, because HA ignores it on an idle one.
- A coverage gate fails when a registered domain has no live sample, unless the domain is on an allowlist kept in the test module. Each allowlist entry carries a reason. An entry whose domain now has a sample fails as stale, following the `tools/client_compat_ignore.txt` convention. For hand-typed attributes the gate also works per attribute (D2).
- Domains with no registered model are ignored. `hassette-codegen check-coverage` already reports those.

Out of scope:

- Any runtime change to `try_convert_state`'s fallback.
- Typing attributes semantically beyond what live values show.
- Allowlisted domains stay unverified. That limitation is named, not solved.
- Deriving hand-typed attribute types from HA source goes to a separate codegen research issue. HA helpers build attributes in `extra_state_attributes() -> dict[str, Any]`, so recovering types needs type-checker inference over HA core, and config-derived values still come back `Any`. Wire types alone also can't tell `"finished"` apart from an ISO timestamp (both `str`), so the live check is needed either way.

## Posture

- **Failure handling:** loud. Any fallback to `BaseState` fails the test, and so do the coverage gates' misses (D2) unless allowlisted.
- **Compatibility:** test infrastructure only. No public API or runtime behavior changes.
- **Scope:** minimal. The live conversion check, helper entities for coverable domains, transitions that populate conditional attributes, and the coverage gate. There's no separate manual audit of #711's models: the live check is the audit for every domain it samples.
- **Rollout:** ships directly.
- **Hardening:** project defaults.
- **Altitude:** build. One session builds it, and the files it touches are stable.

## Decisions

### D1: Which live states does the check convert?

**Situation:** Some attributes exist only mid-lifecycle. A timer's `finishes_at` is present only while the timer is active, and disappears once it finishes. A check that only reads the final `get_states()` snapshot after driving everything never sees an attribute that one transition adds and a later one removes. The alternative is to also convert every `state_changed` new/old state the test observes while it drives transitions.

**Deciding factor:** catching attributes that exist only in intermediate states, which is the #3794 failure shape.

| | A: final snapshot only | B: every state seen during the drive, plus the final snapshot |
|---|---|---|
| Catches `finishes_at`-style transient attributes | no, unless the test snapshots mid-drive by hand per domain | yes, by construction |
| Test complexity | lowest: one `get_states()` | moderate: subscribe to `state_changed` before driving and collect states |
| Failure attribution | entity id plus error | entity id, error, and which transition produced the state |
| What peers do | NetDaemon reads current states and merges metadata across runs to catch conditional attributes | unknown |

**Recommendation:** B, because transient attributes are exactly what a snapshot misses, and collecting events is a small cost against a check that otherwise needs per-domain mid-drive snapshots.
**Pick A instead if** the drive is simple enough that every conditional attribute survives into the final state.

Behavior to pin:
- A conversion failure on any observed state fails the test. It is never only logged (see Assumed on handler exceptions).
- Conversion, the domain gate and the attribute gate judge the same set of observed states.

**Reversibility:** easy (test-internal)
**Ratified:** Chose B over A, to catch attributes that exist only mid-lifecycle (the #3794 shape), accepting an event subscription in the test. Conversion failures fail the test rather than being logged, and conversion and both gates share one set of observed states.

### D2: At what granularity does the coverage gate count a model as verified?

**Situation:** A domain-level gate ("at least one live entity of this domain converted") would still have passed #3794 with an idle, never-run timer, because `last_transition` would be null. An attribute-level gate asks for each declared attribute to be seen with a non-null value at least once, or allowlisted. Models declare about 300 attributes beyond `AttributesBase`'s 5. About 110 of them are hand-typed (manual overrides plus non-codegen models). The roughly 190 on codegen-discovered models take their types from HA source annotations (`codegen/src/hassette_codegen/property_types.py` maps HA's `datetime` to `ZonedDateTime` and so on). `demo` and helper configs won't populate many attributes on rich models (media_player, climate).

**Deciding factor:** catching a mistyped attribute where the type is a guess, without an allowlist so large nobody reads it.

| | A: domain-level for all models | B: domain-level for all, attribute-level for hand-typed models | C: attribute-level for all models |
|---|---|---|---|
| Would have caught #3794 | only if the drive happened to run the timer | yes: an unobserved `last_transition` fails until it's driven or allowlisted | yes |
| Allowlist size (estimate) | about 8 domains (ai_task, assist_satellite, image, infrared, lawn_mower, radio_frequency, tag, wake_word) | about 8 domains plus the hand-typed attributes the drive can't populate (tens) | domains plus most of about 190 discovered attributes no demo populates (well over 100) |
| Distinguishes "verified" from "never sampled" | per domain only | per attribute where types are guesses | per attribute everywhere |
| Maintenance as HA adds attributes | none | a new hand-typed attribute must be driven or allowlisted | every new attribute anywhere needs one or the other |
| What peers do | NetDaemon has no gate; untyped attributes go unreported | unknown | unknown |

**Recommendation:** B, because the risk lives where types are hand-declared. Discovered types come from HA's own annotations, and gating them per attribute mostly grows the allowlist.
**Pick A instead if** you'd rather keep the gate cheap and accept that a conditional attribute can still slip through.
**Pick C instead if** you don't trust codegen's source-annotation types either.
**Reversibility:** easy (the gate's scope is one set in the test)
**Ratified:** Chose B over A and C, to catch never-observed attributes where types are hand-declared, accepting an allowlist of tens of hand-typed attributes the drive can't populate. "Hand-typed" means every attribute of a model whose file isn't in `.generated-manifest` or whose domain's override TOML has `discovery = "manual"`, plus, in a discovered model, each field a `[[property_overrides]]` entry renames, retypes or aliases (widened at the ship-time challenge: a wrong hand-written `wire_name` leaves the field `None` without failing conversion, the #3794 shape). An attribute counts as observed under any key the field accepts (its name, alias or validation aliases). The test derives that set from those sources, never from a hand-kept list. Attribute allowlist entries carry a reason but are not stale-checked. Only domain entries fail as stale, because demo entities change on their own, so whether an attribute appears varies between runs. An outdated attribute entry hides nothing, since every observed value is still converted. Known limitation, accepted: an attribute counts as verified after one observed non-null value, so a second value form that appears only in an undriven state can go unchecked.

### D3: How are the helper entities provided to the system HA?

**Situation:** The system HA config loads `demo:` and one `input_boolean`. Helper domains (timer, counter, input_number, input_select, input_text, schedule) can be declared in YAML or created at test time through hassette's own `Api.helpers` (which wraps HA's helper WebSocket CRUD). script, automation, scene, group and alert have no helper-collection API and need YAML either way. `configuration.yaml` is shared by every system test. Today the only coupling to the config is `tests/system/test_api.py` using `input_boolean.test` and `test_state_proxy.py` asserting `len(entities) > 0`.

**Deciding factor:** one obvious place to see which entities the live HA has.

| | A: all in `configuration.yaml` | B: helpers via `Api.helpers` at test time, the rest in YAML |
|---|---|---|
| Where to look for what's sampled | one file | split across YAML and test code |
| Effect on other system tests | more entities in every run; none of today's tests count entities exactly | helpers exist only during this test, while YAML-only domains still affect every run |
| Dogfoods `Api.helpers` | no | yes (already covered by `tests/integration/test_api_helpers.py` against a mock) |
| Exercises the `.storage`-backed path that UI-created helpers use | no | yes |
| Moving parts | static YAML | create and clean up per run, plus YAML |

**Recommendation:** A, because one file listing every sampled entity is easier to keep in sync with the allowlist, and the YAML-only domains force YAML anyway.
**Pick B instead if** you want `Api.helpers` exercised against a real HA as a side benefit.
**Reversibility:** easy
**Ratified:** Chose A over B, to keep every sampled entity in one config file, accepting more entities in every system-test run and no real-HA exercise of `Api.helpers`. Also accepting that a broken block in the shared config surfaces as a domain-coverage failure, or as an HA startup failure for a YAML syntax error, not as a pointer to the bad line.

### D4: What happens to the JSONL-based conversion test?

**Situation:** `test_fixture_data_parses_as_registered_state_class` converts the Dec 2025 `demo` capture. It runs locally without Docker (the live check runs only in CI's system jobs and wherever Docker is available). The JSONL file itself is used by many other tests as event fixtures (`tests/support/fixtures.py`), so the file stays regardless. Only this one test is at issue.

**Deciding factor:** no test that claims more coverage than it has.

| | A: keep as-is | B: regenerate the JSONL from the system HA with a committed capture script | C: delete the test | D: delete if the live check samples every domain the JSONL test samples, else A |
|---|---|---|---|---|
| Local, Docker-free conversion signal | yes, for the 40 sampled domains | yes, for every domain the live HA covers | none | none if deleted; else as A |
| Churn | none | re-captured events change every test that uses the JSONL fixtures (bus tests and others) | one test removed | one test removed, or none |
| Redundancy with the live check | partial overlap, and it can drift stale | full overlap | none | none if deleted; a labeled partial overlap only when the live check can't cover a JSONL domain |
| New machinery | none | a capture script to maintain | none | one build-time set comparison, nothing committed |

**Recommendation:** A, because it's a cheap local signal and replacing the fixture churns unrelated tests. Its docstring should say it covers only the captured sample and that the live check is the authority.
**Pick B instead if** you want the local signal to match CI's coverage.
**Pick C instead if** a partial local check is worse to you than none.
**Reversibility:** easy
**Ratified:** Chose D over A, B and C, to avoid a stale fixture standing in for coverage. The build deletes the test if the live check samples every registered domain the JSONL test samples. Otherwise it keeps the test with a docstring scoped to the captured sample and lists the uncovered domains under `**Calls made during the build:**`. Either way the JSONL file stays for the other tests that use it.

### D5: Does the check flag live attributes the model doesn't declare?

**Situation:** `AttributesBase` uses `extra="allow"`, so an attribute HA publishes that the model doesn't declare is kept untyped and never causes a conversion failure. The live check could also report those, which would catch HA adding attributes. That's a different drift from #3794's mistyping.

**Deciding factor:** keeping this change on the bug class that bit us.

| | A: don't flag | B: fail, with a per-attribute allowlist | C: report as a test warning, no failure |
|---|---|---|---|
| Catches #3794's class | n/a (it's caught by conversion) | n/a | n/a |
| Catches HA adding attributes | no | yes | visible only to someone reading the logs |
| Noise | none | every demo platform's extras need allowlisting up front | warnings nobody reads |
| Fits the posture (minimal, loud) | yes | goes beyond minimal scope | violates loud |

**Recommendation:** A. Missing attributes degrade gracefully to untyped extras, and codegen's source-driven discovery already picks up new properties for discovered domains.
**Pick B instead if** you want this check to also drive "model is complete" for every sampled domain.
**Reversibility:** easy
**Ratified:** Chose A over B and C, to keep the check on wrong types (the #3794 class), accepting that HA adding an attribute goes unflagged for hand-typed domains.

## Assumed

- The system tests run a real, pinned HA in Docker, and CI runs them on every push. Evidence: `tests/system/docker-compose.yml`, `HA_VERSION=2026.10` in `scripts/docker/.env`, CLAUDE.md "Before Shipping" (`nox -s system_with_coverage` in CI).
- The `demo` integration at the codegen-pinned HA version (2026.10.4) also provides `geo_location` and `remote`, which are absent from the Dec 2025 capture. It doesn't provide `lawn_mower`. Evidence: `homeassistant/components/demo/` platform files at tag 2026.10.4. The build confirms this against the system tests' `HA_VERSION`.
- `try_convert_state` is the only conversion path that falls back to `BaseState`. The strict path raises the validation error. Evidence: `src/hassette/conversion/state_registry.py` `try_convert_state` docstring.
- Hassette records and logs an exception raised inside a bus handler and doesn't propagate it, so a check inside a handler would fail open. Evidence: `src/hassette/core/command_executor.py` (handler execution).
- HA publishes timer `last_transition` as the transition event's suffix, and `finishes_at` only while the timer is active. Evidence: HA core `homeassistant/components/timer/__init__.py` at 2026.10.4 (`_last_transition = event.partition(".")[2]`; `finishes_at` set only while `_end` is set; `async_finish` returns early on an idle timer).
- Codegen-discovered models take attribute types from HA source annotations. Manual-discovery domains take them from the override TOML. Evidence: `codegen/src/hassette_codegen/property_types.py`; `discovery = "manual"` in the override TOMLs under `codegen/src/hassette_codegen/overrides/`.
- No existing system test counts entities exactly, so adding helper entities to the shared config doesn't break them. Evidence: grep of `tests/system/*.py` (only `len(entities) > 0` in `test_state_proxy.py`, and `input_boolean.test` in `test_api.py`).
- Domains with no registered model are reported elsewhere. Evidence: `codegen/src/hassette_codegen/coverage.py` (`hassette-codegen check-coverage`).

## Build

- [x] Implementation and tests committed
- [x] Docs: the system-test table and fixture notes in `tests/TESTING.md`; no user-facing docs (test infrastructure only)
- [x] Ship-time challenge

**Calls made during the build:**
- `todo` comes from a static `shopping_list` config entry in `tests/fixtures/ha-config/.storage/core.config_entries`: `shopping_list` has no YAML setup and the pinned demo has no todo platform. It's static fixture config like the YAML (D3 rejected creating entities at test time, not `.storage`).
- `person` is a YAML person linked to the fixture's admin user (from `.storage/auth`) and given a `picture`, so `user_id` and `entity_picture` are observed instead of allowlisted.
- D4 kept the JSONL test: the live check covers every JSONL domain except `tts`. The pinned demo's `tts` is a legacy provider, which creates no entity, so `tts` is domain-allowlisted. The test's docstring now scopes it to the captured sample.
- Both allowlists live in the test module, each entry with its reason. The domain allowlist is the predicted domains plus `tts`. Attribute entries cover attributes the demo platforms don't publish (demo air_quality pollutants, modern-tracker attributes the legacy demo trackers lack, `group.auto`, demo face-detection attributes).
- The `state_changed` subscription is `on_state_change("*", changed=False, mode="parallel")`. `changed=False` keeps attribute-only changes; `parallel` never drops an event that arrives while the handler runs.
- Failure attribution labels each observed state with its kind (new, old or snapshot) and the drive step running when it arrived. Drive waits match only new states, since an old state is what the entity left.
- The checked models are the registry entries defined inside the installed `hassette` package. CI runs `pytest -m system` with no path, which imports unit-test modules that register their own state classes; the registry is process-global, so without the filter those fail the domain gate.
- The test opts out of CI's `--reruns` (`flaky(reruns=0)`): the drive mutates helpers on the session-scoped HA and isn't idempotent, so a rerun would report a timeout instead of the first failure.
- The drive is linear: the script holds on a long `delay` and is turned off, and the automation is fired with `automation.trigger`. A cross-entity release chain was dropped at the ship-time challenge because it needed an ordering invariant and raced the script's trigger.
- The drive also sets a demo fan's percentage and enables a demo camera's motion detection, so those overridden attributes are observed rather than allowlisted.
- The widened attribute gate found four model fields that are always `None` because HA publishes them under other keys (cover position, number min/max). They're allowlisted naming #3799 rather than fixed here, keeping this change test-only (`known-issues.md` KI-003).
- The `ha-version-bump` skill's Phase 4 names this test and what each of its failures means, since a bump is when it goes red.
- Loading `automation:` and `script:` makes HA create root-owned blueprint folders in the session's temp config copy, so `ha_container` pre-creates them, as it already does for `custom_components`.
- The hand-typed derivation reuses codegen's `load_manifest` and `load_overrides` rather than re-parsing either file.
- Hand-typed models are matched against `.generated-manifest` by path relative to the installed `hassette` package, so the check works whether or not hassette is installed editable.

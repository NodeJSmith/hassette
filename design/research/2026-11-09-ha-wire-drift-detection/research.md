# Research Brief: Catch upstream Home Assistant wire changes before they reach hassette users (#3950)

- **Proposal:** add an early warning for HA changes to hand-written wire models (event payloads, WS/REST models), so a change like 2026.11's `item_id`/`run_id` is flagged before users upgrade HA.
- **Date:** 2026-11-09 · **Status:** Draft · **Flexibility:** Exploring · **Depth:** deep
- **Motivation:** #3949 shipped to users: every `automation_triggered` event was dropped on HA 2026.11 until #3954 (d6aa2f01).
- **Constraints:** solo developer, ~3 known users, GitHub Actions, pre-V1 (no compat shims), prefer lightweight.

**Initiated by:** issue #3950 acceptance criteria: an options comparison with a recommendation, proof that the recommendation would have flagged 2026.11, and follow-up issues to file.

## Bottom line

Do two things together. Neither one alone meets the acceptance criteria.

1. **Add a small live system test for typed HA event payloads.** It drives an automation, a script, a logbook entry and a service call against the container. It asserts two things: each typed event arrived, and `reported_unknown_keys` (the module-global set that `construct_ignoring_unknown_keys` already maintains) stayed empty. This needs no production code change.
2. **Run the non-destructive system suite on a daily schedule against HA's `dev` image.** Track failures in one auto-closing issue, using the existing `ha-version-drift.yml` / `tools/release/drift_check.py` dedupe pattern. Skip `beta`: it adds nothing that `dev` lacks, and for about three weeks of every month it is identical to stable.

With today's code, this pair would have opened an issue on **2026-10-15**. That is the morning after HA #184957 merged to dev, 13 days before 2026.11.0b0, 20 days before HA 2026.11.0, and before hassette v0.61.0, v0.62.0 and v0.63.0 shipped. The demonstration section shows the timeline.

The do-less alternative is the event test alone, against the pinned image. That catches the change only when the pin is bumped, which is after HA ships, so it fails the acceptance criteria. Since d6aa2f01 made new keys harmless at runtime, it would still be a defensible minimum.

## Context

### What prompted this

HA PR #184957 ("Add the run to automation triggered and script started events", merged to dev 2026-10-14, labeled `new-feature`, not `breaking-change`) added `item_id` and `run_id` to `automation_triggered` and `script_started`. Hassette built payloads with `Payload(**event_data)`, so each of those events raised `TypeError`. `dispatch()` (`src/hassette/core/websocket_io.py:336-349`) caught it, `log_dispatch_failure` logged it, and the event was dropped. A user found it on 2026-11-09.

### Current state after d6aa2f01

- **Payload construction:** typed payloads go through `construct_ignoring_unknown_keys` (`src/hassette/events/hass/hass.py:236-257`). It derives the known keys from `dataclasses.fields(cls)`. Unknown keys are dropped and logged once per `(class, key)` per process at DEBUG. The record goes into the module-global `reported_unknown_keys: set[tuple[str, str]]` (`hass.py:21`). The event context (`HassContext`) goes through the same function.
- **Detection:** a new key no longer breaks anything, and nothing notices it either. The issue states this gap itself.
- **Missing required fields:** these still raise `TypeError` and drop every event of that type. Tolerance covers additions only.
- **Live coverage:** `tests/system/test_state_models.py` (#3800, 2026-11-04) already fires `automation.trigger` on `automation.state_model_automation` and `script.turn_on` on `script.state_model` (DRIVE, lines ~162-165). Its only subscription is `on_state_change("*")` (~243). The issue says nothing fires an automation or script, which is out of date: they do fire, and nothing listens to their events. The fixture automation has `id: state_model` (`tests/fixtures/ha-config/configuration.yaml:~82`), which matters because HA adds `item_id`/`run_id` to `automation_triggered` only when the automation has a `unique_id` (HA `automation/entity.py`, `if self.unique_id:`).
- **The pin:** the pinned image moved from 2026.10 to 2026.11 in d6aa2f01 itself (2026-11-09). Even a payload assertion against the pin would have stayed green through HA's release.

### Key constraints

- Lightweight, with no new runtime machinery.
- Loud-failure posture in tests, with allowlist entries that carry reasons and fail when stale (spec 145, `design/specs/145-live-state-model-validation/design.md`).
- Runtime parsing stays tolerant.

## Evidence: how often HA actually changes these shapes

Source: read-only git analysis of `~/source/core` over `2023.12.0..2026.11.1`. Each `-G`/`-S` hit on the event fire sites was checked against its diff.

- **Hassette-modeled event payloads:** 1 key change in about 2.9 years (#184957, two events in one commit), roughly 0.35 per year. `call_service`, `service_registered`/`removed`, `component_loaded`, `user_added`/`removed`, `logbook_entry` and the `state_changed` envelope had no key changes.
- **All HA event key changes, including events hassette doesn't model:** about 7 commits, roughly 2.4 per year. Examples are `device_registry_updated` #148425 and #149734, `area`/`floor` `reorder` #156802, and `state_reported` #148932.
- **WS frame keys** (`websocket_api/messages.py`, `auth.py`): no changes found. Notable REST and WS changes were #181590 (service-call errors now return JSON 400/500, 2026.10) and the logbook REST entries gaining `item_id`/`run_id` (additive). I reviewed `commands.py` by commit subject only.
- **Lead times:** shape changes land on dev 0-27 days before b0. #184957 landed 14 days before. The b0 to .0 window was exactly 7 days, Wednesday to Wednesday, in 14 of 15 months (2026.1 was 9). Total merge to release runs about 3-7 weeks. One sample (#149734) merged one day after b0 and was cherry-picked into the beta.

The ~0.35/year rate is low enough that frequency alone doesn't justify an elaborate system. A cheap canary is justified because it also covers state models, WS/REST, startup and the companion integration in one run.

## Feasibility Analysis

### HA image tags (verified against `home-assistant/core/.github/workflows/builder.yml` and live Docker Hub data)

| Tag | Points to | Notes |
|---|---|---|
| `dev` | Nightly build of the `dev` branch (`cron "0 2 * * *"`), version `YYYY.MM.0.devYYYYMMDDHHMM` | 29 of the last 30 scheduled builds succeeded; the one failure was 2026-10-27. Occasional extra builds, e.g. at branch cut. |
| `beta` = `rc` | Newest non-dev version | Between betas it points at the latest stable. On 2026-11-09, `beta`, `rc`, `stable`, `latest` and `2026.11` all had the same digest (2026.11.1). |
| `stable` / `latest` / `YYYY.MM` | Latest stable | The pin uses the floating `YYYY.MM` tag (`scripts/docker/.env:27`, `HA_VERSION=2026.11`). |

`beta` is a useful canary only during the 7-day window. HA merges to `dev` and cherry-picks into the release branch, so a key change reaches `dev` first, or at the same time in the rare cherry-pick case. `dev` is a superset of `beta` for this purpose.

### Plumbing already in place

- **Image override:** `tests/system/conftest.py:145-151` pins `HA_ACCESS_TOKEN`, `SYSTEM_HA_PORT` and `HASS_HASSETTE_VERSION`, but passes `HA_VERSION` through from `os.environ`. Compose reads `tests/system/.env`, a symlink to `scripts/docker/.env`, and the process environment wins over it. So `HA_VERSION=dev uv run nox -s system` already targets the dev image, for both the HA service and the `hass-hassette` init container. No code change is needed.
- **In-process tests:** `startup_context` runs `Hassette` in the pytest process. Only `test_project_layouts.py` and `test_sigint_shutdown.py` spawn subprocesses. So a test can read `hassette.events.hass.hass.reported_unknown_keys` directly. The unit regression test `tests/unit/events/test_hass_event_unknown_keys.py:38` already monkeypatches that set.
- **Event collection:** `make_event_collector` (`tests/system/conftest.py:~395`) plus `bus.on(topic=Topic.HASS_EVENT_AUTOMATION_TRIGGERED / HASS_EVENT_SCRIPT_STARTED / HASS_EVENT_LOGBOOK_ENTRY, ...)` (`src/hassette/types/enums.py:141-153`) and `bus.on_call_service` provide it. `test_api.py:61-82` shows the pattern.
- **Issue tracking:** the single-tracking-issue pattern exists in `ha-version-drift.yml` plus `tools/release/drift_check.py`. `find_existing_issue` (`:58-87`) dedupes on "open issue with label X" and deliberately raises on lookup failure. `ensure_label` (`:35`) creates the label. The workflow opens an issue, comments on repeat, and closes it when the condition clears.
- **Runtime:** the CI system jobs take about 6 minutes each (run on d6aa2f01, 2026-11-09). The job timeout is 20 minutes.

### What works against this

- **`-x` in the nox session:** `_run_system_tests` (`noxfile.py:436-470`) hardcodes `-x`, so a canary run stops at its first failure. A canary wants the full failure list, so it needs a separate session or a pass-through to drop `-x`.
- **Unrelated failures on `dev`:**
  - `test_hass_hassette.py` depends on the pinned `hass-hassette` release (v0.5.0) loading on dev HA. The `ha-version-bump` skill already treats that test as non-blocking.
  - The fixture `.storage` files (`core.config_entries` 1.5, `core.config` 1.3, `onboarding` 4) migrate forward, but a dev schema change could stop HA from starting, which hits the 60 s `STARTUP_TIMEOUT`.
  - `test_state_models.py`'s domain and attribute gates will flag demo or attribute drift on dev. That is wanted signal about state models, but it isn't about event wire shapes.
  - Ordinary system-test flakes are mitigated by `--reruns 2`.
- **External noise baseline:** NetDaemon's nightly `stable`+`beta` integration CI failed 7 of its last 20 scheduled runs. The causes weren't established, so treat this as a caution, not a measured rate for hassette.

### What would need to change

| Area | Files | Effort | Risk |
|---|---|---|---|
| Event payload system test | new `tests/system/test_hass_event_payloads.py`; maybe `tests/fixtures/ha-config/configuration.yaml` (a second automation without `id:`) | Small | Low. Test-only, and it reuses the `ha_container` fixture. |
| Canary nox session | `noxfile.py` (session without `-x`, non-destructive, `test_hass_hassette` deselected) | Small | Low |
| Canary workflow | new `.github/workflows/ha-dev-canary.yml`; reuse `tools/release/drift_check.py` helpers, possibly with a small entry point for "test outcome" mode | Small–Medium | Low. It never gates PRs. |
| Bump skill | `.claude/skills/ha-version-bump/SKILL.md` Phase 5 (check the canary issue) | Small | None |

## Options Evaluated

### Comparison

| Option | Cost | Catches | When, relative to HA .0 / hassette release | Noise | Maintenance |
|---|---|---|---|---|---|
| **A. Live event-payload test, pinned image** | Small: one test module | New keys (via `reported_unknown_keys`) and removed required keys (event never arrives) on driven events. Not type changes, since dataclasses don't check types. | Only at the pin bump, after HA .0. For 2026.11 that was 2026-11-09, 5 days after release. | Very low | Low; same allowlist convention as spec 145 |
| **B. Daily canary on `dev` (needs A to see event shapes)** | Small–Medium: workflow, nox session, issue routing | Everything A catches, plus state-model drift, startup/WS/REST breakage, companion-integration breakage | Day after the dev merge: 1-4 weeks before HA .0, so usually before the next hassette release | Medium: dev-only breakage and flakes. Bounded by one tracking issue that closes on green. | Triage one issue when it opens; the workflow is mostly static |
| B′. Same, on `beta` | Same as B | Same as B | b0, 7 days before .0 (2026-10-28 for this case). The other ~3 weeks it duplicates stable. | Lower than dev | Same as B |
| B″. Same, on `stable` | Same as B | Same as B, but only after release | At HA .0, before the pin bump | Low | Mostly redundant with `ha-version-drift.yml` plus the bump skill |
| **C. Upstream source diffing** | Medium to build, ongoing to tune | Raw file diff: everything, buried in noise. TypedDict watch: would have **missed** #184957, because `automation_triggered`/`script_started`/`call_service`/`user_*`/`logbook_entry` have no TypedDict in HA. | Dev-merge day | High: 69 commits touched the candidate files in 2026.10→2026.11 with 1 true positive. File moves (`automation/__init__.py` → `entity.py`, 2026-10-08) break path-keyed watchers. | High: the file list and constant extraction drift with HA refactors |
| D. Generate event payloads from HA source (codegen) | Large | Same as C for the 3 events with TypedDicts; nothing for the other 6 | Pin bump | — | High |
| E. Do nothing more (tolerance only, d6aa2f01) | None | Nothing; new keys are now harmless, and removals still drop events | Never; a user report | None | None |

### Option A + B (recommended combination)

**How it works:**

1. **The test.** A new system test subscribes collectors to `automation_triggered`, `script_started`, `logbook_entry` and `call_service`. It clears `reported_unknown_keys`, then drives `automation.trigger`, `script.turn_on`/`turn_off`, `logbook.log` and one plain service call. It asserts:
   - at least one typed event of each type arrived;
   - `reported_unknown_keys` is empty, or equals a reasoned allowlist that fails when stale, following the spec 145 / `tools/client_compat_ignore.txt` convention.

   The positive-receipt assertion is load-bearing. Without it an empty set could mean "nothing arrived", and a removed required key, which drops the event, would pass silently.

   `reported_unknown_keys` also records `HassContext` and `RawStateChangePayload` drops. Every event carries a context, so the test checks the envelope for free.
2. **The schedule.** A daily workflow (about 04:00 UTC, after the 02:00 UTC dev build) runs the non-destructive system suite once, on one Python version, with `HA_VERSION=dev`, `test_hass_hassette.py` deselected, and no `-x`.
3. **Routing.** On failure, create or update one issue labeled e.g. `ha-dev-canary`. The body carries the failing test IDs, the run link and the HA dev version (from `/api/config`). Comment only when the set of failing tests changes; close with a comment on the next green run. It never gates PRs.

**Why `dev` over `beta`:**

- `dev` gives 1-4 weeks of lead time against `beta`'s 7 days, and for #184957 it was 13 days earlier.
- `beta` is identical to stable for about three weeks a month.
- `dev` builds are reliable (29 of 30).
- The extra noise, from in-flight dev breakage that gets fixed before beta, costs at most one issue that auto-closes.
- Running both doubles the noise sources for one week a month of corroboration. If dev proves too noisy in practice, switching the matrix value to `beta` is a one-line change.

**Why daily rather than weekly:**

- A weekly run can miss a late cherry-pick. #149734 merged one day after b0 and shipped 6 days later.
- Comment-on-change dedupe makes daily no noisier than weekly in issue traffic.
- Public-repo Actions minutes are free.
- If flakes make daily open-and-close churn annoying, twice weekly (Monday and Thursday) still covers every sample in the history table.

**Pros:**

- Uses machinery that already exists: the `HA_VERSION` passthrough, in-process `reported_unknown_keys`, `make_event_collector`, and `drift_check.py`'s dedupe.
- No production code change.
- One canary covers events, state models, WS/REST and startup.

**Cons:**

- A canary failure needs triage to tell "HA changed a wire shape" from "dev is broken".
- Type changes in dataclass payloads stay invisible.
- Coverage is limited to the events the fixture can drive. `user_added`/`removed`, `service_removed` and `component_loaded` arrive mostly before subscription or need destructive setup.

**Effort:** Small–Medium overall. The test is small; the workflow plus nox session is small to medium.

**Dependencies:** none new.

### Option C detail (assessed, not recommended)

Measured against the local core clone:

- **Candidate files:** `core.py`, `setup.py`, `auth/__init__.py`, the three registries and `components/{automation,script,logbook,trace}`.
- **Commit volume:** 22-69 commits per release cycle (2026.7 to 2026.11), with one true positive in about three years for modeled events.
- **Path drift:** #184957's code landed in `automation/entity.py` six days after it moved there from `__init__.py`.
- **Breaking-change labels:** none of the relevant PRs (#184957, #186898, #186134, #181590, #148932, #148425) carried `breaking-change`, so a label watcher also misses.
- **Narrower watcher:** a watcher keyed on `async_fire` calls with modeled `EVENT_*` constants would be low-noise, but it is a custom AST tool tracking HA's internals. That is a heavier version of codegen for a change that happens about every three years.

The live test reads what HA actually sends, which makes it the better source of truth. That matches the conclusion of `design/research/2026-11-04-ha-state-model-drift/prior-art.md` for state models.

### Do less

**Option A alone** catches new or removed keys at the next pin bump, before a hassette release built against that HA, but after HA ships. Since d6aa2f01, a new key no longer hurts users at runtime. The residual user-facing risk is a removed or renamed required key, which happened 0 times in about 2.9 years for modeled events. If the canary's triage cost turns out unwelcome, A alone is the honest fallback. It does not meet #3950's acceptance criteria.

## Demonstration: would A + B have flagged 2026.11?

| Date | Event | A + B (dev) | A alone (pin) | B′ (beta) |
|---|---|---|---|---|
| 2026-10-14 09:17 UTC | #184957 merged to HA dev (88becb3e787) | | | |
| 2026-10-15 ~02:25 UTC | Nightly dev image `2026.11.0.dev202610150225` built from dev | **Canary fails 10-15 → issue opened** | green (pin 2026.10) | green (`beta` = 2026.10.x) |
| 2026-10-22 | hassette v0.60.0 | fix could ship here | | |
| 2026-10-28 | HA 2026.11.0b0 | | | **fails, issue opened** |
| 2026-10-29 / 11-02 | hassette v0.61.0 / v0.62.0 | | | fix could ship in v0.61.0 |
| 2026-11-04 | HA 2026.11.0 and hassette v0.63.0 | | green until the pin bump | |
| 2026-11-08/09 | User upgrades; #3949 reported; pin bumped in the fix PR | | would fail at the pin bump, **after** users were hit | |

**Why the test fails on that image:**

- **Against the pre-fix code (dcaeea40):** `AutomationTriggeredPayload(**data)` and `ScriptStartedPayload(**data)` raise `TypeError`, so `dispatch()` drops the events and the "at least one `automation_triggered` / `script_started` arrived" assertion fails. HA adds the keys to the automation event only because the fixture automation has `id: state_model`. The script event always carries them.
- **Against current code, for the next such change:** the event arrives, `reported_unknown_keys` contains e.g. `("AutomationTriggeredPayload", "item_id")`, and the emptiness assertion fails with the class and key named.

**Confidence:**

- **Direct:** the merge date (git) and tag dates (git).
- **Supported:** that the 10-15 nightly contained the commit. Builder cron 02:00 UTC, the commit was on dev the morning before, and the dev version string comes from Docker Hub tag data; I didn't pull that image.
- **Inferred:** that the test would fail as described. It follows from reading `create_event_from_hass`, `construct_ignoring_unknown_keys` and the HA diff; nothing was run.

## Audit: hand-written models that parse HA wire data

Legend:

- **TS** = tolerant-silent (drops unknown keys)
- **TP** = tolerant-preserving (`extra="allow"`)
- **U** = unvalidated (TypedDict or raw dict)
- **S** = strict

**Live** means it is exercised against the real HA container in `tests/system/`.

| Model | File | HA source | New key | Removed/renamed key | Type change | Failure lands at | Live coverage |
|---|---|---|---|---|---|---|---|
| `RawStateChangePayload` | `events/hass/hass.py:~167` | event `state_changed` | TS, DEBUG once | `entity_id`/`old_state`/`new_state` required → `TypeError`, event dropped | unchecked | `dispatch` → `log_dispatch_failure` (ERROR) | yes: `test_bus.py`, `test_state_proxy.py` |
| `HassStateDict` (state inside events, `get_states`, REST `states/*`) | `events/hass/raw.py:20` | many | U | U; fails later at model conversion | U | state conversion | yes: `test_state_models.py` |
| `CallServicePayload` | `hass.py:34` | `call_service` | TS | `domain`, `service` required → drop | unchecked | dispatch, drop | fired incidentally, never asserted |
| `ComponentLoadedPayload` | `hass.py:44` | `component_loaded` | TS | `component` required → drop | unchecked | dispatch, drop | none |
| `ServiceRegistered/RemovedPayload` | `hass.py:51,59` | `service_registered/removed` | TS | `domain`, `service` required → drop | unchecked | dispatch, drop | none |
| `LogbookEntryPayload` | `hass.py:67` | `logbook_entry` | TS | `name`, `message` required → drop | unchecked | dispatch, drop | none |
| `UserAdded/RemovedPayload` | `hass.py:77,84` | `user_added/removed` | TS | `user_id` required → drop | unchecked | dispatch, drop | none |
| `AutomationTriggeredPayload` | `hass.py:91` | `automation_triggered` | TS; now declares `item_id`, `run_id` | `name`, `entity_id` required → drop | unchecked | dispatch, drop | **none live**; unit test with a hand-written shape |
| `ScriptStartedPayload` | `hass.py:~104` | `script_started` | TS | `name`, `entity_id` required → drop | unchecked | dispatch, drop | **none live**; unit test only |
| `EntityRegistryUpdatedPayload` | `hass.py:118` | `entity_registry_updated` | — | — | — | **never constructed**; no branch in `create_event_from_hass`, no `Topic` in `enums.py`; events take the raw-dict fallback | n/a |
| Untyped events (fallback) | `hass.py:~358` | any other event type | U, raw dict | U | U | — | yes: `fire_event` test |
| Event envelope (`origin`, `context`, `time_fired`) | `hass.py:~265` | every event | — | direct index → `KeyError`, **every** event dropped | `time_fired` parse raises | dispatch, drop | yes, implicitly |
| `HassContext` | `events/base.py:32` | `context` of every event | TS | all 3 fields required → **every** event dropped | unchecked | dispatch, drop | yes, implicitly |
| `Context` (pydantic) | `models/states/base.py:19` | state `context`, `ServiceResponse.context` | TS (pydantic ignore, no log) | all default `None` | `ValidationError` | state conversion | yes: `test_state_models.py` |
| Generated state/attribute models | `models/states/*` | `get_states`, `state_changed` | TP | per-field; required → `ValidationError` | pydantic coercion, else error | `try_convert_state` → `BaseState` fallback + WARNING; strict paths raise to the app | yes: `test_state_models.py` with domain and attribute gates |
| `BaseEntity` and subclasses | `models/entities/base.py:21` | REST `states/{id}` | TP | as state models | as state models | raises to the app | none specific |
| `HistoryEntry` | `models/history.py:7` | REST `history/period` | TS | 5 fields required → `ValidationError` | strict `Instant` | raises to the app | yes: `test_api.py::test_get_history` (default flags) |
| `ServiceResponse` | `models/services.py:6` | WS `call_service` + `return_response` | TS | `context` required → `ValidationError`, raised **after** HA applied the call | strict | raises to the app | **none** |
| `HaCoreConfig` | `core/ha_core_config.py:13` | WS `get_config` | TS | lat/lon/elevation/time_zone required | strict | caught: WARNING, previous value kept | yes, implicitly at connect |
| Helper `*Record` (8 domains) | `models/helpers/*.py` | WS `<domain>/list/create/update` | TP | `id`, `name` required → `ValidationError` | strict on declared fields | raises to the app | counter only (`test_helpers.py`); **7 domains none** |
| `get_states`/`get_services`/`get_panels`/`get_config` returns | `api/api.py:376-432` | WS | U (top-level type check only) | U | top level only | raises to the caller | `get_config`, `get_states` yes; `get_services`/`get_panels` none |
| logbook / calendar / state_raw / set_state / fire_event returns | `api/entity_data.py` | REST | U, raw JSON | U | U | — | `set_state`, `fire_event` yes; logbook and calendar none |
| WS auth, result and subscription frames | `core/websocket_service.py:593-620`, `core/websocket_responses.py`, `core/websocket_io.py:139-185` | WS protocol | U, reads only the keys it needs | missing `type` → `KeyError`, reconnect; missing result `id` → WARNING, request times out | — | reconnect loop or caller timeout | yes, every system run |

hassette-wire (`wire/`), `client/` and `cli/client.py` parse **hassette's own** web API, not HA's, so they are out of scope.

**Takeaways:**

- **Strict models left uncovered by d6aa2f01:** none for new keys. Every HA-facing model is now TS, TP or U on additions.
- **Where risk remains:** removed or renamed required fields and type changes. Hand-written dataclasses don't check types; pydantic models raise.
- **Highest blast radius:** the envelope and `HassContext`. A removed field there drops every event, including `state_changed`, which hassette needs for state.
- **Riskiest unobserved paths:** `ServiceResponse`, the 7 helper domains with no live test, and `automation_triggered`/`script_started`, which the recommended test fixes.
- **A claim I rejected:** the audit agent suspected `HistoryEntry` breaks with `no_attributes=True`. HA's REST history uses `State.as_dict()`, which always emits an `attributes` key (`homeassistant/components/recorder/models/state.py:134`), so the suspicion doesn't hold for REST. Not a follow-up.

## Concerns

### Technical risks

- **Canary failures that aren't wire changes.** On `dev`, `test_state_models.py`'s domain and attribute gates will fail on demo or attribute drift, and allowlisted domains appearing on dev fail as stale. Treat this as early codegen-bump signal, not noise. Name it in the tracking-issue body so triage starts there.
- **Fixture `.storage` on dev.** A schema bump that HA can't migrate from 1.3/1.5 would show up as a 60 s startup timeout. That is a real signal about the fixture, but it masks everything else until fixed.
- **Process-global set.** The system suite runs in one process (`-n 0`), so `reported_unknown_keys` accumulates across tests. The new test must clear it before its drive and read it right after.
- **Type changes stay invisible** for dataclass payloads. Adding runtime type checks (typeguard or similar) would be new machinery for a change with no observed precedent. Not recommended now.

### Complexity risks

- **One more scheduled workflow and label.** It is in the same shape as three existing drift workflows. GitHub disables scheduled workflows only after 60 days without repo activity, which doesn't apply here.

### Maintenance risks

- **Allowlist upkeep.** A key hassette decides not to model needs an allowlist entry with a reason. Stale entries fail, as in spec 145.
- **Canary issue ownership.** Someone has to read the canary issue. See Open Questions.

## Open Questions

Resolved 2026-11-09:

- [x] **Where the canary issue surfaces.** The tracking issue alone. GitHub notifications plus the `ha-version-bump` skill reading the open canary issue before each bump (follow-up #5) are enough; no digest change or push notification.
- [x] **Dropped typed events.** Keep dropping them. A typed event that fails to construct is already logged at ERROR by `log_dispatch_failure` (`core/websocket_inbound.py`). An untyped fallback would hand a dict to handlers written for typed events, so they would fail later in their own code or in DI extraction. In a typed framework, the canary's early warning is the right answer, not a fallback. No issue filed.
- [x] **`test_hass_hassette.py` in the canary.** Excluded.

Scope: the follow-ups form a small milestone, *HA Drift Canary*, placed after *Diagnostic Evidence* and before *Testing API Redesign*. #1, #2, #4 and #5 are in it, with #4 included so the canary also sees service-response and helper-record shapes. #3 is cleanup and stays milestone-less.

## Recommendation

Build **A + B on `dev`, daily, with one auto-closing tracking issue**.

- **Confidence that it would have caught 2026.11 about 3 weeks before HA's release:** Supported, from git dates, the builder cron, Docker Hub tag data and a read of the parsing path. Nothing was executed.
- **Confidence that dev noise stays tolerable:** Inferred. HA's dev builds succeed 29/30, but hassette has no history yet of running its system suite against dev, and NetDaemon's nightly shows non-trivial failure counts with unknown causes.
- **What would change the recommendation:** if the first month of canary issues is mostly unrelated dev breakage, drop to `beta` (same workflow, one value) and accept 7 days of notice.
- **Option C:** not worth building. The live test is cheaper and reads what HA actually sends.

### Suggested next steps

1. File the follow-ups below (done: #3958-#3962). #1 and #2 are the core; the rest are audit-driven.
2. Build #1 first: it is useful on the pinned image alone and is a prerequisite for #2 to see event shapes.
3. After a month of canary runs, review the noise and decide between dev and beta, and between daily and twice weekly.

## Follow-up issues

Filed 2026-11-09 as #3958 (1), #3959 (2), #3962 (3, milestone-less), #3960 (4) and #3961 (5). All but #3962 are in the *HA Drift Canary* milestone. The drafts below are kept as written.

**1. Add a live system test for typed Home Assistant event payloads**
*Labels:* `type:enhancement`, `area:testing`, `area:bus`, `topic:events`, `size:small`

Typed payloads now drop unknown keys silently (#3949), and no system test listens to the events the fixture already causes. `test_state_models.py` fires `automation.trigger` and `script.turn_on`, but subscribes only to `state_changed`. Add `tests/system/test_hass_event_payloads.py`:

- It clears `hassette.events.hass.hass.reported_unknown_keys`.
- It collects `automation_triggered`, `script_started`, `logbook_entry` and `call_service` with `make_event_collector`, and drives `automation.trigger` (on an automation with an `id:`, so HA emits `item_id`/`run_id`), `script.turn_on`/`turn_off`, `logbook.log` and one service call.
- It asserts (a) at least one typed event of each type arrived, and (b) `reported_unknown_keys` is empty or matches a reasoned allowlist whose stale entries fail (spec 145 convention).

Acceptance: against the pre-#3954 code on HA 2026.11, the test fails on (a).

**2. Run the system suite daily against Home Assistant's dev image and track failures in one issue**
*Labels:* `type:CICD`, `area:testing`, `size:medium`

Add `.github/workflows/ha-dev-canary.yml`: a schedule at about 04:00 UTC plus `workflow_dispatch`.

- It runs a new nox session (non-destructive system marker, no `-x`, `test_hass_hassette.py` deselected) on one Python version with `HA_VERSION=dev`. `tests/system/conftest.py` already passes `HA_VERSION` through to compose.
- On failure, it opens or updates a single issue labeled `ha-dev-canary`, reusing `find_existing_issue`/`ensure_label` from `tools/release/drift_check.py`. The issue lists the failing test IDs, the HA dev version from `/api/config`, and the run link.
- It comments only when the failing set changes, and closes the issue on the next green run.
- It never gates PRs.

Depends on #1 to see event shapes. Rationale and the 2026.11 timeline are in the #3950 research brief.

**3. Delete or wire up the orphaned `EntityRegistryUpdatedPayload`**
*Labels:* `type:bug`, `area:bus`, `topic:events`, `size:small`

`EntityRegistryUpdatedPayload` (`src/hassette/events/hass/hass.py:118`) is defined but `create_event_from_hass` has no `entity_registry_updated` branch, and `Topic` has no matching member. Those events arrive as untyped `Event` with a raw dict. Either add the branch and a topic, using `construct_ignoring_unknown_keys` and HA's `EventEntityRegistryUpdatedData` TypedDict as the field reference (it has create/remove and update variants), or delete the class. Pre-V1, deletion is fine if no docs reference it; check `docs/` first.

**4. Add live coverage for `call_service(return_response=True)` and the untested helper domains**
*Labels:* `type:enhancement`, `area:api`, `area:testing`, `size:medium`

The audit for #3950 found two HA-facing pydantic models with required fields and no live test:

- `ServiceResponse` (`models/services.py:6`). Its `context` is required, and a validation error is raised to the app after HA has already applied the call.
- Seven of eight helper `*Record` domains (`models/helpers/`). Only counter is exercised (`test_helpers.py`).

Add system tests that call a response-returning service against the fixture HA, and that list/create/update each helper domain the fixture config can host. That way the dev canary (#2) sees these shapes too.

**5. Check the dev canary and event payloads in the ha-version-bump skill**
*Labels:* `type:enhancement`, `area:testing`, `size:small`

`.claude/skills/ha-version-bump/SKILL.md` Phase 5 checks only the developer blog, which never covers additive event changes. #184957 had no post and no `breaking-change` label. Add a step: before bumping, read the open `ha-dev-canary` issue, if any, and resolve or explicitly carry over its findings. Optionally, run `hassette-codegen check-coverage --ha-release-tag dev` in the canary workflow. `ha_source.py` clones with `--branch`, so `dev` should work, but whether `check-coverage` exits non-zero on gaps wasn't verified.

## Sources

- HA builder workflow (image tags, nightly cron): https://github.com/home-assistant/core/blob/dev/.github/workflows/builder.yml
- Docker Hub tag data: https://hub.docker.com/v2/repositories/homeassistant/home-assistant/tags
- HA PR #184957: https://github.com/home-assistant/core/pull/184957
- NetDaemon CI against stable+beta, nightly: https://github.com/net-daemon/netdaemon/blob/0116c9815d0a22eb7ae38df574c55f5636af0d8e/.github/workflows/ci_build.yml
- pyscript CI (no HA dev or beta): https://github.com/custom-components/pyscript/blob/master/.github/workflows/validate.yml
- HomeAssistantAPI base model (pydantic default, extra ignore): https://github.com/GrandMoff100/HomeAssistantAPI/blob/main/homeassistant_api/models/base.py
- AppDaemon config models: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/models/config/http.py
- HA events docs (no shape-stability promise found): https://contributors.home-assistant.io/core/integrations/events/
- Local `~/source/core` git history (tags 2023.12.0 through 2026.11.1), read-only.

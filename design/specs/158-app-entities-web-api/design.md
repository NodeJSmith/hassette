# Design: Serve declared entities and their commands over the web API

**Date:** 2026-11-21
**Status:** built
**Mode:** sketch
**Issues:** #4219
**Parent:** design/specs/155-hacs-app-entities/design.md
**Prior art:** design/research/2026-11-16-app-declared-ha-entities/prior-art.md

## Summary

Breakdown item 3 of the HACS App Entities milestone. #4218 (spec 157) made app instances declare
buttons, switches and sensors through `self.integration`, persisted them, and gave `IntegrationService`
(`src/hassette/core/integration_service.py`) an in-process `dispatch_command`. Nothing serves them yet.
This change puts each instance's declared entities and their state in the app listing with the revision
and boot identifier (parent D3), adds the command route hass-hassette will call (parent D4, D5), the
`hassette-client` methods and exceptions for it. The monitoring UI view is deferred to a follow-up
issue (D7).

Where each new piece lives:

- **Wire models:** `DeclaredEntity` (shape D6) in `wire/src/hassette_wire/apps.py`, carried as
  `AppInstance.entities`; `boot_id` and `revision` on `AppListResponse` (D4); `EntityCommandResponse`,
  the command route's 202 body (D1); `IntegrationPlatformName` (`Literal["button", "switch", "sensor"]`)
  and its `OpenIntegrationPlatformName` alias in `wire/src/hassette_wire/literals.py`, typing `platform` on
  both models (D6); two new `ProblemCode`s (D3) in `wire/src/hassette_wire/problems.py`;
  the schema version bump (Posture) in `wire/src/hassette_wire/health.py`.
- **Domain snapshot:** in `src/hassette/schemas/app_snapshots.py`, a frozen `DeclaredEntityInfo`
  (a `Declaration` and its `EntityState`, both from `hassette.integration.declarations`) and
  `AppInstanceInfo.entities: tuple[DeclaredEntityInfo, ...] | None = None`; web may not runtime-import
  `core`, so the facade converts `IntegrationService`'s `CommittedEntity` to `DeclaredEntityInfo`.
  `app_instance_from` (`src/hassette/web/mappers.py`) maps them to `DeclaredEntity`, converting an
  `Instant` value to its ISO 8601 string with offset and a `Date` to its ISO date (parent D12; the
  stored form, `encode_value` in `declarations.py`); attributes are already JSON objects (spec 157 stores
  them as a JSON round-trip copy) and pass through unchanged.
  `AppFullSnapshot` is unchanged (`AppRegistry.get_full_snapshot()` builds it too, and the registry
  stays integration-unaware, D5): `app_list_response_from(full, *, boot_id, revision)` takes the two
  values as keyword-only arguments, and every constructor of `AppListResponse` (the mapper, tests,
  seed scripts) passes them.
- **Listing join:** a new synchronous `RuntimeQueryService` method (`src/hassette/core/runtime_query_service.py`)
  that only the `GET /api/apps` route calls, taking the `list[AppManifestInfo]` from
  `overlay_listed_manifest_rows` and returning a frozen `AppListingSnapshot` (in
  `src/hassette/schemas/app_snapshots.py`): the manifests with each
  instance's `entities` attached from `IntegrationService.entities()` by `(app_key, instance_name)`,
  plus `boot_id` and `revision` read in the same step (D4, D5). The route builds `AppFullSnapshot` from
  those manifests and passes `boot_id`/`revision` to the mapper.
  `overlay_listed_manifest_rows` and `overlay_manifest_rows` stay entity-free, so `GET /api/apps/{app_key}`
  and the dashboard grid (`/app-grid`, `src/hassette/web/routes/telemetry.py`) carry `entities: null`.
- **Command routes:** in `src/hassette/web/routes/apps.py` beside the app action routes:
  `POST /api/apps/{app_key}/instances/{instance_name}/buttons/{key}/press` and
  `POST /api/apps/{app_key}/instances/{instance_name}/switches/{key}/turn_on` / `turn_off` (D1),
  answering as D2 says. D2's existence check is a new helper in `routes/apps.py` that runs only after
  `dispatch_command` returns `NOT_RUNNING`, reading `AppRegistry.get_manifest`, `configured_names` and
  `get_instances`; it must not reuse the pre-dispatch helpers (`_require_addressable_instance`,
  `_orphan_app_permitted`, `_orphan_instance_permitted`), whose ordering is D2's rejected option B. Each declares `APP_KEY_CODES` plus `app_not_found`, `instance_not_found`,
  `instance_not_running` and `entity_not_declared` in `problem_responses`), calling `IntegrationService.dispatch_command` through the `hassette` dependency;
  `CODE_STATUS`/`CODE_DESCRIPTIONS` in `src/hassette/web/errors.py` gain D3's codes.
- **Client:** `press_button(app_key, instance, key)` and `set_switch(app_key, instance, key, on)` (D1),
  each returning `EntityCommandResponse`, in `client/src/hassette_client/client.py`; the two exceptions
  (D3) in `client/src/hassette_client/errors.py` as `ConflictError` subclasses; the floor bump (Posture)
  in `client/src/hassette_client/version.py`; the new routes in `tools/client_compat_requests.py`.
- **Generated frontend schema:** `frontend/openapi.json` and `frontend/src/api/generated-types.ts`,
  regenerated with `uv run python scripts/export_schemas.py --types`. No UI components change (D7).
- **Docs:** `docs/pages/web-ui/api-errors.md` (the new codes) and `docs/pages/web-ui/python-client.md`
  (the new methods, including that an instance's entities are usable only while its `status` is
  `running`, and that only `GET /api/apps` fills `AppInstance.entities`); `docs/pages/core-concepts/apps/integration-entities.md` only if it says where
  declared entities can be seen.

Out of scope: entity state on `/ws` and client WebSocket subscriptions (#4220); anything in
hass-hassette (#72, #73); any monitoring UI view of declared entities (D7); moving persistence to `hassette-state.db`
(the parent's Addendum follow-up).

## Posture

- **Failure handling:** loud failure. A command answers 202 once its event is published, or a typed 409
  (parent D5). No retries.
- **Compatibility:** additive wire only. A released `hassette-client` and hass-hassette keep parsing the
  listing (`nox -s client_compat`), and a platform an older client doesn't know must not break its parse
  of the listing. `API_SCHEMA_VERSION` and `MIN_API_SCHEMA_VERSION` both go to 7 under the client-floor
  rule (v0.65.0 reports 6). hassette's Python API may break freely.
- **Scope:** minimal: Breakdown item 3 without its monitoring UI (D7). No frontend components change;
  only the generated schema and types are regenerated.
- **Rollout:** ships outright, no flag.
- **Hardening:** project defaults. The command route logs INFO with the peer address only when a command
  is dispatched, as `trigger_job` does; `IntegrationService.reject_command` already logs a WARNING per rejection.
- **Altitude:** build; one session builds it.

## Decisions

### D1: What does the command route look like?

**Situation:** parent D4 settles an HTTP command route on hassette's web API and D5 that it returns once
dispatched, but neither names a path, method or body. `dispatch_command(app_key, instance_name, key,
platform, value)` raises `ValueError` for a sensor target, a switch command without a bool, or a button
command with a value. hass-hassette receives HA service calls `button.press`, `switch.turn_on` and
`switch.turn_off`, already resolved to one action each. The existing per-instance routes are
`/api/apps/{app_key}/instances/{instance_name}/{action}` (`app_target_path` in the client). Later
platforms (`number`, `select`) would carry a value.

**Deciding factor:** each HA service call maps to one route with nothing left to validate.

| | A: One fixed verb per HA service, no body | B: One generic route with a body | C: Platform in the path, value in a body |
|---|---|---|---|
| Example | `POST …/instances/{instance}/buttons/{key}/press`; `POST …/switches/{key}/turn_on`, `…/turn_off` | `POST …/instances/{instance}/entities/{key}/command` `{"platform": "switch", "value": true}` | `POST …/instances/{instance}/entities/switch/{key}` `{"value": true}` |
| `dispatch_command`'s `ValueError` | Unreachable: each route passes a fixed platform and value | 422 `validation_failed` from the body model, plus a mapping for anything it misses | 422 for a bad value; sensor path needs a 404 or 422 |
| Matches HA's service vocabulary | Yes, one route per service | No | Partly |
| Client methods | `press_button(app_key, instance, key)`, `set_switch(app_key, instance, key, on)` (two routes) | One `send_command(…, platform, value)` | One per platform |
| A later `number`/`select` | One more route each (`…/numbers/{key}/set_value` with a body) | No new route, more body validation | No new route |
| Peers | ESPHome: one command message per platform (`ButtonCommandRequest`, `SwitchCommandRequest`); HA's services | None found | None found |

**Recommendation:** A, because hass-hassette maps each HA service call straight to one route, no request
carries a value that can be wrong, and that matches ESPHome's per-platform commands and HA's own
services. The 202 body is a small response model naming the app key, instance, key and platform, with
`status: OpenAcceptedStatus = "accepted"` as `JobTriggerResponse` has, so an older client parses a later
status value instead of failing; its docstring says accepted means the command event was published, not
that the handler ran.
**Pick B instead if** you expect many more platforms soon and want one route to cover them. **Pick C
instead if** you want the platform visible in the path but one route per platform.
**Reversibility:** hard once released (routes are wire contract hass-hassette depends on).
**Ratified:** Chose one fixed-verb route per HA service with no body (`buttons/{key}/press`, `switches/{key}/turn_on`, `switches/{key}/turn_off`) over a generic command route or a platform path with a value body, so each HA service call maps to one route and `dispatch_command`'s `ValueError` can't be reached from the web, accepting one more route per future platform. Sketch challenge (Finding 5): the 202's `status` reuses the open `OpenAcceptedStatus` (`"accepted"`) rather than a closed `"dispatched"` literal, so adding a status later never breaks an older client's parse.

### D2: What does the route answer for an app, instance or key hassette doesn't know?

**Situation:** `IntegrationService.admit_command` is the single admission check (spec 157 Addendum): no
live owner for `(app_key, instance_name)` → `NOT_RUNNING`; key not committed on that platform →
`NOT_DECLARED`. A live owner exists only for a committed, not-yet-stopped instance, including a running
orphan whose config block was removed. The app action routes check config first and answer
`app_not_found` / `instance_not_found` (404), with orphan exceptions for `stop`. Config and ownership can
disagree mid-reload. hass-hassette only ever sends targets it read from the listing; a hand-caller or
third-party client with a retry policy needs to tell "gone" from "restarting".

**Deciding factor:** one authority decides admission, with no window where two checks disagree, and each
rejection says whether a retry can succeed.

| | A: Syntax check on `app_key`, then admission alone | B: Config checks (404s) first, then admission | C: Admission first; a not-running rejection for a target that doesn't exist answers 404 |
|---|---|---|---|
| Who decides admission | Owner map only | Config, then owner map | Owner map only |
| Unknown app or instance | 409 `instance_not_running` | 404 `app_not_found` / `instance_not_found` | 404 `app_not_found` / `instance_not_found` |
| Running orphan instance (config block removed) | Admitted: it has a live owner | 404 unless an orphan exception is added | Admitted before any config read |
| Retry meaning of `instance_not_running` | Ambiguous: gone for good or restarting | Exists but not running | Exists but not running |
| Codes hass-hassette must map | Two conflicts (parent D5) | Two conflicts plus two existing 404s | Two conflicts plus two existing 404s |
| Race with a config reload | None: one check | Config and ownership can disagree, admitting or refusing wrongly | Only which rejection a refused command gets (404 or 409) |
| Code | None | Route-level checks plus orphan rules | One existence lookup after a `NOT_RUNNING` |

**Recommendation:** C, because admission stays the owner map's alone, so a running orphan stays
commandable, while a target that doesn't exist gets the 404 the app routes already use and
`instance_not_running` means only "exists but isn't running now". `app_key` keeps the existing
`invalid_app_key` 400. After `dispatch_command` returns `NOT_RUNNING` (its WARNING already logged by `reject_command`), the route answers `app_not_found`
when the registry has no manifest for `app_key` and tracks no instance of it, `instance_not_found` when
the instance is neither among the app's configured names nor tracked by the registry, and
`instance_not_running` otherwise. `NOT_DECLARED` is always `entity_not_declared` (409, parent D5).
**Pick A instead if** you want hass-hassette to map only two codes and don't care about hand-callers.
**Pick B instead if** you want config to gate commands before ownership is consulted.
**Reversibility:** easy before release.
**Ratified:** Chose admission first with an existence check refining only a `NOT_RUNNING` rejection into `app_not_found` / `instance_not_found` (404) over admission alone or config 404s first, so the owner map stays the single admission authority, a running orphan stays commandable, and `instance_not_running` means "exists but not running now", accepting two more codes for hass-hassette to map and a reload-time race that only changes which rejection a refused command gets. Accepted limitation (sketch challenge, Finding 7): a running orphan of an app whose whole config block was removed is admitted but never listed (`listed_apps` drops removed apps), so only a caller that already knows its target can command it. Revised by the sketch challenge (Finding 6): an earlier ratification chose admission alone.

### D3: What are the new problem codes and client exceptions called?

**Situation:** parent D5's re-challenge makes the two conflicts wire contract, each with its own
`hassette-client` exception, and hass-hassette translates each one. `ProblemCode` names are permanent
before 1.0 (renaming is breaking). Existing 409s are named for the condition (`job_not_registered`,
`action_in_progress`). Parent D2 keeps "entity" meaning an HA entity; on the wire these are the declared
entities HA sees.

**Deciding factor:** names that say the condition and stay true if another route reuses them.

| | A: `instance_not_running` / `entity_not_declared` | B: `integration_instance_not_running` / `integration_entity_not_declared` |
|---|---|---|
| Exceptions | `InstanceNotRunningError`, `EntityNotDeclaredError` | `IntegrationInstanceNotRunningError`, `IntegrationEntityNotDeclaredError` |
| Reusable by a later route targeting a running instance | Yes, with the same meaning | Reads as integration-only |
| Reads clearly in hass-hassette's error table | Yes | Yes, longer |
| Matches existing code names | Yes (condition-named) | Adds a feature prefix none have |

**Recommendation:** A, because the codes name the condition the way existing ones do, and "not running"
is true of any instance-targeted route that needs a running instance.
**Pick B instead if** you want the codes scoped to the integration feature so nothing else reuses them.
**Reversibility:** hard once released (codes are wire contract).
**Ratified:** Chose `instance_not_running` / `entity_not_declared` with `InstanceNotRunningError` / `EntityNotDeclaredError` over integration-prefixed names, to name the condition as existing codes do and let a later instance-targeted route reuse them, accepting that the names don't say they came from the integration feature.

### D4: Where do the revision and boot identifier appear? (may supersede part of parent D3)

**Situation:** `IntegrationService` keeps one hassette-wide `revision` counter, bumped on each declaration
commit and each changed `set()`, and a per-boot `boot_id`. Nothing tracks a per-instance value. Parent
D3's re-challenge says the boot identifier travels once per listing response and "the counter per
instance". hass-hassette applies a listing for an instance if its revision is equal to or newer than the
last it applied for that instance (a listing is a full snapshot), and a `/ws` delta (#4220) only if
strictly newer. `AppSummary`, and so `AppInstance`, is also served by `GET /api/apps/{app_key}` and the
dashboard grid (`AppGridEntry`). The listing route awaits its DB read, then overlays runtime state with
no await, so the entities and the counter can be read as one snapshot.

**Deciding factor:** hass-hassette's apply rules hold with the least new state and no half-usable fields.

| | A: Boot id on `AppListResponse`; each `AppInstance` carries its own last-change counter | B: Both on every `AppInstance` | C: Both on `AppListResponse` only; the counter is the snapshot's |
|---|---|---|---|
| Parent D3's apply rules | Hold | Hold | Hold: one snapshot at counter R satisfies "equal or newer" for every instance, and a later delta carries a larger counter |
| New service state | Per-instance last-change counter, updated where `revision` is bumped | Same | None |
| `GET /apps/{key}` and the grid | Carry a revision with no boot id beside it | Self-contained | Carry neither (entities are listing-only, D5) |
| Payload | One id per response | The 32-char id repeated per instance | One id and one int per response |
| hass-hassette can skip unchanged instances | Yes | Yes | No (re-applies every poll, as it does today) |
| Parent wording | Matches | Boot id contradicts "once per listing" | Supersedes "counter per instance" |

**Recommendation:** C, because the listing is one snapshot at one counter value, so a per-instance number
adds service state the apply rules don't need, and keeping both fields on the listing alone means no
response carries a revision it can't be compared by. The entities and the counter are read with no await
between them. This supersedes parent D3's "the counter per instance" (the boot id stays once per listing).
Both fields are required, with no defaults: `boot_id: str`, `revision: int`. Their docstrings state
parent D3's apply semantics: compare `boot_id` before `revision`; `revision` is ordered only within one
`boot_id`; the listing reflects every commit through `revision`.
**Pick A instead if** you want hass-hassette to skip unchanged instances, or keep the parent's per-instance
wording. **Pick B instead if** you want every response carrying entities to be comparable on its own.
**Reversibility:** hard once released (wire fields), easy before.
**Ratified:** Chose both the boot identifier and the counter once on `AppListResponse`, the counter being the snapshot's value read with no await between it and the entities, over a per-instance last-change counter or both fields on every `AppInstance`, so parent D3's apply rules hold with no new service state and no response carries a revision it can't compare, accepting that hass-hassette re-applies every instance on each poll; supersedes parent D3's "the counter per instance", which came from an auto-applied re-challenge finding with no recorded reasoning, while the comb follow-up's single hassette-wide counter stands. Sketch challenge (Findings 3, 4): both fields are required with no defaults, and their docstrings state parent D3's apply semantics.

### D5: Which responses carry entities, and where does the data join them?

**Situation:** `AppInstanceInfo` is built by `AppRegistry` (`_info_from_entry`, `build_manifest_info` in
`src/hassette/core/app_registry.py`), which knows nothing about integration entities. Every app response
goes through `overlay_runtime_state` via `RuntimeQueryService.overlay_manifest_rows`
(`src/hassette/core/runtime_query_service.py`), the web's facade onto runtime state: the listing
(`overlay_listed_manifest_rows`), `GET /api/apps/{app_key}` (`overlay_manifest_rows`) and the dashboard
grid (`AppGridEntry`, which also calls `overlay_listed_manifest_rows`).
Only the listing carries D4's `boot_id` and `revision`, and D7 leaves no UI reading entities anywhere.
Web routes may not runtime-import `core` (`web-no-core` in `tools/check_module_boundaries.py`).

**Deciding factor:** no public response carries entity state it can't order against the revision,
without teaching the registry about integrations.

| | A: `RuntimeQueryService` attaches entities after every overlay | B: `AppRegistry` reads `IntegrationService` while building infos | C: Each route fetches entities and passes them to the mapper | D: A `RuntimeQueryService` method only the listing route calls attaches entities |
|---|---|---|---|---|
| Registry stays integration-unaware | Yes | No: a new dependency on a sibling service | Yes | Yes |
| Responses carrying entities | Listing, `GET /apps/{key}`, grid | Same | Only routes that pass them | Listing only; the others carry `entities: null` (D6) |
| Entity state with no revision beside it | On `GET /apps/{key}` and the grid | Same as A | Depends on the route | None |
| One snapshot with D4's counter | Yes, in the same sync step | Yes | Yes | Yes |
| Placeholder infos for never-started instances | Covered: attached by key after building | Each construction site must add it | Covered | Covered |
| Grid payload per dashboard poll | Grows with every declared entity | Grows | Unchanged | Unchanged |
| Reversibility | Removing entities from a response later is breaking | Same as A | Additive | Additive: #4387 can add entities where the UI needs them |

**Recommendation:** D, because with D7 ratified the only consumer is hass-hassette's listing poll, the one
response with a revision, and adding entities to another response later is additive while removing them
is not. A new facade method, called only by the `GET /api/apps` route after the shared overlay, joins by
`(app_key, instance_name)` and reads the entities and D4's counter in the same synchronous step; the
shared overlays stay entity-free because the grid uses `overlay_listed_manifest_rows` too.
**Pick A instead if** you want every response carrying `AppInstance` to show entities, accepting state
with no revision beside it on `GET /apps/{key}` and the grid. **Pick B instead if** you want
`AppInstanceInfo` complete wherever it's built, including the CLI paths that read the registry directly.
**Pick C instead if** you want each route to decide for itself.
**Reversibility:** easy before release; adding responses later is additive.
**Ratified:** Chose a new `RuntimeQueryService` method that only the `GET /api/apps` route calls to attach entities (`GET /apps/{key}` and the grid carry `entities: null`, D6) over attaching them after every overlay, the registry reading `IntegrationService`, or per-route fetches, so no public response carries entity state it can't order against D4's revision and the registry stays integration-unaware, accepting that #4387 has to add entities to `GET /apps/{key}` if its UI needs them there. Revised by the sketch challenge (Finding 2): an earlier ratification chose every overlay, whose reason (UI consumers) went away when D7 was ratified. Sketch comb: the join is its own facade method, because the grid also calls `overlay_listed_manifest_rows`.

### D6: What does a declared entity look like on the wire?

**Situation:** spec 157 stores each entity as one row with typed columns: key, platform, name, optional
`default_entity_id`, a switch's `initial`, a sensor's unit, device class, state class and options, plus a
value and attributes (spec 157 D4). Parent D12: a value on the wire is a JSON scalar or `null`; a
timestamp sensor's value is stored as ISO 8601 with offset and a date as an ISO date. Open-valued wire
fields use an `Open<Type>` alias that an older client parses as `UnknownValue` under
`LENIENT_CONTEXT` (`wire/src/hassette_wire/lenient.py`). A pydantic discriminated union fails
validation on an unknown discriminator, which would fail the whole listing for a released client.

**Deciding factor:** a released client keeps parsing the listing when a platform or field is added.

| | A: One flat model, open `platform`, platform fields nullable | B: Discriminated union per platform |
|---|---|---|
| Older client meets a new platform | Parses it as `UnknownValue` and can skip it | Listing fails to validate |
| Type precision | Sensor fields are `None` on buttons and switches | Each member has only its fields |
| Generated TypeScript | One type; UI branches on `platform` | Narrowed union |
| Adding a field | Additive | Additive per member |
| Fits existing wire | `AppInstance` and listener models are flat | Only `/ws` messages are unions (and #4220 skips unknown types) |

**Recommendation:** A, because the compatibility posture rules out a listing a released client can't
parse. The model is `DeclaredEntity` (not a `*Entity` HA name, parent D2) with `key`, `platform` (open),
`name`, `default_entity_id`, `unit`, `device_class`, `state_class`, `options` (`list[str] | None`),
`value` (`int | float | str | bool | None`; a button's is `null`), and `attributes` (`dict[str, Any]`). `device_class` and
`state_class` are plain strings, so a class HA adds later never fails a parse. `initial` is left out:
the value already reflects it, and HA has no use for it. `AppInstance.entities` is
`list[DeclaredEntity] | None = None`: a list in key order on `GET /api/apps` (`[]` for an instance that
declares nothing), and `None` meaning "not included" on every other response (D5).
**Pick B instead if** typed narrowing in the UI and client matters more than an older client surviving a
new platform.
**Reversibility:** hard once released.
**Ratified:** Chose one flat `DeclaredEntity` model with an open `platform` and nullable platform fields over a per-platform discriminated union, so a hass-hassette pinning an older `hassette-client` skips an entity on a platform it doesn't know instead of failing its whole `/api/apps` poll (which would take every app's entities, framework ones included, unavailable in HA), accepting that code reading the model checks `platform` before using sensor fields rather than getting type narrowing. Sketch comb: `AppInstance.entities` is `None` (not included) on responses other than `GET /api/apps` rather than `[]`, chosen over keeping `[]` with a docstring caveat, so no response reads as an instance declaring nothing when it wasn't included.

### D7: Where does the monitoring UI show an instance's declared entities?

**Situation:** the app page (`frontend/src/pages/app-detail.tsx`) has overview, handlers, code, logs and
config tabs for one instance; a multi-instance app's parent view shows instance cards and hides the
handlers tab. Each declared button or switch already appears as a listener on the handlers tab
(spec 157 D1). The real-user corpus has one app with about 25 sensors and several apps with one or two
buttons.

**Deciding factor:** the entities are easy to find without crowding the instance's overview.

| | A: A section on the instance's overview tab, hidden when empty | B: A new "entities" tab, instance-only, with a count badge | C: Rows on the handlers tab | D: No UI in this issue; a parked follow-up issue |
|---|---|---|---|---|
| 25-sensor app | Long section pushes the overview down | Its own scrollable view | Mixed into handler rows | n/a until the follow-up |
| Discoverable | Only by scrolling the overview | Tab with a count, like handlers | Hidden among listeners | Handlers tab only (buttons and switches as listeners) |
| Apps declaring nothing | Nothing shown | Tab hidden (no badge, no tab) | Nothing shown | Nothing shown |
| Sensors (no handler) | Fit | Fit | Don't fit a handlers view | Not visible in the UI |
| New UI surface | One section | One tab and route segment | None | None; generated types only |
| Work spent on a UI due for a rewrite | Some | Most | Least | None |

**Recommendation (not taken; see Ratified):** B, because an instance can declare dozens of sensors, and a tab with a count badge
matches how handlers are already found. The tab shows each entity's platform, name, key and suggested
entity id, and its value with unit and attributes; it appears only when the instance declares entities.
**Pick A instead if** most apps will declare one or two entities and a new tab feels heavy. **Pick C
instead if** you want no new surface and accept sensors not fitting there. **Pick D instead if** the
monitoring UI is about to be rewritten and few users would see the view before then.
**Reversibility:** easy.
**Ratified:** Chose shipping no UI in this issue and filing the declared-entities view as #4387, milestone-less and parked under `epic:ui-redesign`, over an entities tab, an overview section or handlers-tab rows, to spend no work on a UI due for a rewrite while the user base is small, accepting that declared sensors are invisible in the monitoring UI until then. This overrides `.claude/rules/design-completeness.md` for this change, supersedes spec 157 D8 (its PR-body criterion is not met here; the PR body says it moved to the follow-up issue), and supersedes the parent's Done-when clause "the monitoring UI shows each instance's declared entities", which is dropped from the HACS App Entities milestone. The PR still regenerates `frontend/openapi.json` and `frontend/src/api/generated-types.ts`.

## Assumed

Carried from the parent ledger (`design/specs/155-hacs-app-entities/design.md`) and spec 157, still
holding against current code:

- The command route admits a key only while its instance is running and it declares that key, and
  answers a typed conflict otherwise, reload and `starting` included; it returns once dispatched.
  Parent D5. In code, "running" is `IntegrationService.admit_command`'s live-owner check (spec 157
  Addendum), and `dispatch_command` returns `DISPATCHED`, `NOT_RUNNING` or `NOT_DECLARED`
  (`src/hassette/integration/declarations.py` `CommandDispatchResult`).
- Both conflicts are 409, each its own `ProblemCode` and `hassette-client` exception. Parent D5.
- A boot identifier plus a hassette-wide counter starting at 0 each boot, in memory only, bumped by
  #4218's code; this change serves them. Parent D3; `IntegrationService.boot_id` / `revision`.
- No per-feature capability gate: the schema floor bump (Posture) is the only version check. Parent
  Posture; `client/src/hassette_client/version.py` docstring; `tools/check_client_floor.py`.
- Entity keys are lowercase letters, digits and `_`, unique per instance across all three platforms.
  Parent D11; spec 157 build calls.
- Switch state is set by the handler itself, never by the framework after a toggle. Spec 157 D11
  (supersedes parent D7); no effect on the route.
- A removed instance appears in the listing with `in_current_config` false while it is still tracked,
  and is absent once stopped or pruned; hass-hassette treats both as removable. Parent D13;
  `AppRegistry.build_manifest_info` (`display_names`).
- The listing reads entities from `IntegrationService`'s memory, which is updated only after each write
  commits (spec 157 D10), and holds every persisted instance's set, stopped ones included, from the
  startup load. Spec 157 D10 moves the listing to DB rows once spec 132 lands; spec 132 is not built
  (no `StatusProjector` in `src/`). Evidence: `IntegrationService.on_initialize`, `entities()`.
- A dropped or superseded press shows only as a near-miss or cancelled invocation, never in the 202.
  Spec 157 D1.
- A declared entity is available only while its instance's `status` is `running`; a down instance's
  entities stay listed as unavailable, and a press in the stale-poll window after a stop gets the 409
  (accepted). Parent D9. `status == running` matches ownership because the declaration commit, which
  makes the instance the owner, lands before the `RUNNING` status write. Evidence:
  `src/hassette/core/app_lifecycle_instances.py` (`initialize_instance`). The `python-client.md` docs
  for the command methods state this rule, worded as "commands are accepted while the instance is
  running, and may be accepted briefly around its start and stop" (admission also holds between the
  commit and the `RUNNING` write, and during the app's own `on_shutdown`; spec 157 Addendum).
- Web routes reach runtime services through the `hassette` dependency and may not runtime-import
  `core`. Evidence: `tools/check_module_boundaries.py` (`web-no-core`).
- The latest release reports `API_SCHEMA_VERSION = 6`. Evidence: v0.65.0's
  `wire/src/hassette_wire/health.py`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- Command routes register through one `entity_command_route(path)` helper in `routes/apps.py`, so the three routes can't disagree on status, response model or declared codes.
- A timestamp sensor's value goes on the wire as `Instant.format_iso()` (`2024-01-01T12:30:00Z`), the same string `encode_value` stores; `Z` is the ISO 8601 UTC offset, so it meets parent D12's "with offset".
- The web test stub's `IntegrationService` (`wire_integration_service` in `tests/support/web_mocks.py`) derives `dispatch_command`'s result from its declared entities: an instance in the map counts as running. Integration tests and the client compat fixtures share this one fake instead of each scripting results.
- The INFO line on dispatch isn't pinned by a test: `tests/TESTING.md`'s no-caplog rule, and `trigger_job`'s identical line isn't pinned either.
- The client compat fixtures declare one entity per platform on `my_app`'s instance (`DECLARED_ENTITIES` in `tools/client_compat_live_state.py`), so the listing fixtures fill every `DeclaredEntity` field for the released client to parse.
- `docs/pages/core-concepts/apps/integration-entities.md` is unchanged: it never says where declared entities can be seen.
- The open alias is `OpenIntegrationPlatformName`, not the Summary's `OpenIntegrationPlatform`: the wire's `Open<Type>` alias must name its literal (`test_open_alias_marker_names_its_own_type`), and naming the literal `IntegrationPlatform` would collide with hassette's own `IntegrationPlatform` enum.
- `tools/check_wire_compat.py` reports D4's required `boot_id`/`revision` as a break for a new client talking to an older server, which the API schema floor bump already accepts. Following the repo's convention for every ignore-file entry, the two lines go in `tools/wire_compat_ignore.txt` and the PR is titled `feat!` with a `BREAKING CHANGE:` footer naming the client's new floor. Giving the fields defaults would have reversed D4.
- A parity test pins the wire's `IntegrationPlatformName` to hassette's `IntegrationPlatform` enum (`tests/unit/test_wire_vocabulary_typing.py`), since the open alias would otherwise hide a fourth platform missing from the wire.

## Addendum

- 2026-11-21: The Summary's `DeclaredEntityInfo` wasn't kept. It copied `CommittedEntity` field for field, so `CommittedEntity` moved from `core/integration_service.py` to `hassette.integration.declarations` (beside `Declaration` and `EntityState`, which `schemas` and `web` may import), and `AppInstanceInfo.entities` holds it directly. The listing join no longer converts anything. Found by the ship-time clean-code gate.

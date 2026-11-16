# Design: App-declared Home Assistant entities

**Date:** 2026-11-16
**Status:** ratified
**Mode:** sketch
**Issues:** #3993, #2439
**Prior art:** design/research/2026-11-16-app-declared-ha-entities/prior-art.md

## Summary

Apps that need a dashboard trigger, a user-facing toggle or a published value rely today on helpers made
by hand in Home Assistant (`input_button`, `input_boolean`, `input_number`) that exist only for hassette
to listen to or write. The definition lives in HA and the behavior in the app, and every new app needs a
manual HA step. The real-user corpus has about ten trigger-only buttons, several app-state booleans, and
about 25 `input_number`s used as read-only sensors by one app.

This milestone lets an app instance declare HA buttons, switches and sensors in code. hassette owns the
declarations and the state; hass-hassette (the HACS integration) creates the entities, shows the state,
and routes presses and toggles back to the owning instance's handler.

Where each new piece lives:

- **Declarations, entity state and command dispatch:** a new per-app-instance child resource on `App`
  (its attribute name is D2), backed by a core service that holds every instance's persisted
  declarations and entity state (switch and sensor values with their attributes), plus the in-memory
  state revision (D3). Persistence is hassette's database.
- **Wire contract:** new `hassette_wire` models for a declared entity and its state, carried per
  `AppInstance`, a command route on hassette's web API (D4) and the `hassette-client` method that calls it.
- **Push channel:** entity messages on hassette's `/ws` stream and WebSocket subscriptions in
  `hassette-client` (D3).
- **HA side:** hass-hassette's coordinator and three new entity classes on its existing button, switch
  and sensor platforms, under a device model settled by D1.
- **Monitoring UI:** each instance's declared entities and their state shown on its app page, since they
  are persisted and served by the web API (the repo's design-completeness rule).
- **Testing seam:** the app-testing harness gains declarations and simulated presses/toggles.

Out of scope: `binary_sensor`, `number`, `select` and other platforms; entities shared across instances
of an app; per-instance framework entities (start/stop per instance); building #1449's cached entity
access (only its name is settled here, D2); webhooks (#594) and `@template` (#46), which this unblocks.

## Posture

- **Failure handling:** loud failure. Entities go unavailable while hassette or the owning instance is
  down; commands are not retried or queued.
- **Compatibility:** hassette's Python API may break freely (pre-V1). hass-hassette's existing unique_ids,
  devices and config flow are protected. The wire contract stays additive, so a released hass-hassette
  keeps working against newer hassette and ignores entities it doesn't know.
- **Scope:** minimal: button, switch and sensor, each declared by and belonging to one app instance.
- **Rollout:** ships outright; the hassette release lands before the hass-hassette release that needs it.
  No feature flag. The new client method raises hassette's API schema floor (the client-floor rule), so a
  hass-hassette pinning that client shows its existing `unsupported_version` repair against an older
  hassette until the user upgrades hassette; no per-feature capability gate.
- **Hardening:** project defaults. Command handlers get the standard handler telemetry and error isolation.
- **Altitude:** milestone; the work spans hassette and hass-hassette over several PRs, and each issue is
  picked up with its own build-altitude sketch.

## Decisions

### D1: How do app instances appear in Home Assistant?

**Situation:** hass-hassette v0.1 gives each *app* one device (identifier `app_key`) holding the
framework entities (start/stop switch, reload button, status sensor), linked under a hub device.
Declared entities belong to an *instance*. Seven apps in the real corpus run several instances, and the
first migration case (`cameras_cast`: bedroom and living_room) needs one "Show cameras" button per TV,
each naturally in a different HA area. HA assigns areas per device (an entity can override its area).
32 of the corpus's 39 apps have a single instance.

**Deciding factor:** each instance's entities group and place naturally in HA without changing anything
v0.1 users already have.

| | A: Instance device on demand, under the app device | B: All on the app device | C: Instance device only for multi-instance apps |
|---|---|---|---|
| Area per instance | Native: assign the instance device to a room | Per-entity override only | Native for multi-instance apps |
| Device count (corpus) | One extra device per instance that declares entities | No new devices | Extra devices only for 7 apps |
| Stable when instance count changes | Yes: a device exists iff the instance declares entities | Yes, but entity names need an instance prefix only when there are several instances, so names shift | No: adding a second instance moves the first instance's entities to a new device |
| Mirrors hassette's model (app → instances) | Yes | No | Partly |
| v0.1 devices and entities untouched | Yes | Yes | Yes |
| Entity naming | `has_entity_name` on the instance device ("Bedroom Show cameras") | Names must carry the instance by hand | Mixed |
| Peers | ESPHome/MQTT: device per physical unit, entities under it | — | — |

**Recommendation:** A, because each instance becomes its own placeable HA device without touching v0.1's
app devices, and creating it only when the instance declares something keeps single-instance apps that
don't use the feature at one device.
**Pick B instead if** you'd rather never add devices and accept setting areas per entity. **Pick C
instead if** you want instance devices only where they help with placement and accept entities moving device when an instance is added.
**Reversibility:** hard (device identifiers and placement are user-visible; moving entities between
devices later loses user area assignments).
**Ratified:** Chose an instance device created on demand under the app device over keeping everything on the app device or instance devices only for multi-instance apps, to give each instance a placeable HA device without touching v0.1's app devices, accepting one extra device per instance that declares entities.

### D2: Which concept owns `self.entities`?

**Situation:** #1449 proposes `self.entities` as cached, no-await access to behavior-bearing wrappers for
*any* HA entity (`self.entities.light["light.kitchen"].turn_on()`), parallel to `self.states`. This
milestone needs an app attribute for entities the app *declares and owns*. Both can't have the name.
Framework rule: keep the public surface small; a new helper goes on the most specific component.

**Deciding factor:** the name reads correctly in app code and doesn't collide with HA's vocabulary.

| | A: Declared entities own `self.entities` | B: #1449 keeps `self.entities`; declared go on `self.integration` | C: #1449 keeps it; declared on a new `self.owned_entities` |
|---|---|---|---|
| Reads in app code | `await self.entities.add_button(...)` | `await self.integration.add_button(...)` | `await self.owned_entities.add_button(...)` |
| Matches HA vocabulary | No: in HA "entities" means all entities, which is #1449's meaning | Yes | Yes |
| Failure mode is legible | "entities" doesn't say an integration is required | Name says it needs hass-hassette | Partly |
| Natural home for #594 webhooks / #46 templates later | No | Yes, all need the integration | No |
| Grab-bag risk | Low | Medium: must stay limited to integration-backed features | Low |
| #1449 impact | Must pick a new name | None | None |

**Recommendation:** B, because `self.entities` keeps HA's meaning for #1449, and `self.integration` names
the dependency the declarations actually have, which is also where webhooks and templates will need to go.
**Pick A instead if** you expect #1449 never to ship and want the shortest name for the feature people
will use. **Pick C instead if** you don't want one attribute to collect future integration features.
**Reversibility:** easy now (nothing shipped); hard after a release (pre-V1 breaks are allowed but cost users edits).
**Ratified:** Chose `self.integration` for declared entities, with handle types that don't reuse the `*Entity` names (`ButtonEntity`, `SwitchEntity` already mean references to HA entities), over giving declared entities `self.entities` or a dedicated `self.owned_entities`, to keep "entity" meaning a reference to an HA entity as in HA, NetDaemon and AppDaemon, accepting that `self.integration` must stay limited to features that go through the integration.

### D3: How does entity state get from hassette to Home Assistant?

**Situation:** hass-hassette polls hassette's web API every 30 s and refreshes about a second after it
sends an action. hassette has a `/ws` stream for its web UI; `hassette-client` has no WebSocket support,
and the WS contract has no compatibility check yet (#2439). Every peer pushes state; none polls it.
Button presses don't need this path; switches need it after a toggle; sensors need it whenever the app
changes a value.

**Deciding factor:** app-pushed state reaches HA quickly enough to drive automations, at the least new
transport.

| | A: Poll only | B: Subscribe to hassette's `/ws` | C: hassette calls an integration service over its own HA WS |
|---|---|---|---|
| Sensor latency | Up to 30 s | Sub-second | Sub-second |
| Switch after toggle | After the handler completes, up to 30 s (a lag D5 and D7 create; a delayed refresh would also fix it) | Sub-second after the handler completes | Sub-second after the handler completes |
| New transport | None | WS support in `hassette-client`, entity messages on `/ws`, #2439 first | A second direction (hassette → HA services), the ADR-0004 shape the transport revisit moved away from |
| Reconnect behavior | n/a | Subscribe, then resync from the full REST list on every (re)connect | Integration must detect a missing resync (Node-RED's standing bug class) |
| Peers | None poll state | ESPHome: HA connects out, device pushes | Node-RED, NetDaemon integration (deprecated) |
| Fits #2439 being in the pool | Makes it unnecessary for this milestone | Yes | No |

**Recommendation:** B, because it keeps the one transport direction hass-hassette already uses and gives
push latency, with the REST list as the resync point so a dropped stream degrades to polling instead of
stale state.
**Pick A instead if** a 30 s sensor lag is acceptable for a first cut and you'd rather defer WS client
work (then #2439 leaves the milestone). **Pick C instead if** you'd accept a second transport to avoid
adding WS to `hassette-client`.
**Reversibility:** easy to go A → B later; hard to unwind C.
**Ratified:** Chose subscribing to hassette's `/ws` with a full-list REST resync on every (re)connect over polling only or hassette calling an integration service, to get push latency over the one transport direction hass-hassette already uses, accepting WebSocket support in `hassette-client` and #2439 landing first. Challenge (Finding 1) settled the sync model: the 30 s poll keeps applying entity state after push is live, so push only lowers latency and a lost delta heals within one poll; each instance carries a revision that increases on every entity state change, on both the listing and `/ws`, and the integration applies a value only if its revision is newer than the last it applied for that instance; the integration subscribes before it fetches on (re)connect. Comb follow-up: a revision is a boot identifier hassette generates at each start plus a hassette-wide counter that starts at zero each boot; both are served on the listing and on `/ws`. The integration compares counters within one boot and drops its last-applied marks when the boot identifier changes, so revisions never go backwards across restarts, a pruned and re-added instance (D13), or a recreated database, with nothing persisted. A declaration commit (D9) bumps the counter too. Re-challenge: the boot identifier travels once per listing response and once per `/ws` entity message, the counter per instance; counters may skip values; a listing with no revision is never met, because the schema floor (Posture) keeps a new integration off pre-feature hassette.

### D4: How does a press or toggle in Home Assistant reach the app?

**Situation:** hass-hassette already sends app actions to hassette over HTTP and turns failures into HA
errors the user sees. `hassette.send` instead fires an HA event that hassette receives over its own HA
WebSocket, and can't tell the caller whether anything handled it.

**Deciding factor:** the user sees a failure in HA when the command can't be delivered.

| | A: HTTP command route on hassette's web API | B: HA event over hassette's HA WS |
|---|---|---|
| Delivery failure visible in HA | Yes: request fails → HA error toast | No: the event fires whether or not hassette is listening |
| Matches existing integration code | Yes, same path as app actions | Same path as `hassette.send` |
| Auth | Existing web API token | HA's own |
| Handler telemetry | Same handler-invocation machinery either way | Same |
| Peers | ESPHome: commands on the HA → device link | Node-RED: down the runtime's WS |

**Recommendation:** A, because it reuses the integration's existing action path and its error mapping, so
an unreachable hassette or a stopped instance shows as an error on the button.
**Pick B instead if** you want commands to work when HA can reach hassette's HA connection but not its web API.
**Reversibility:** easy (internal to the two repos).
**Ratified:** Chose an HTTP command route on hassette's web API over an HA event on hassette's HA WebSocket, to surface delivery failures in HA through the integration's existing action path and error mapping, accepting that commands need hassette's web API reachable from HA. `hassette.send` stays an HA event: it is a broadcast to any number of bus listeners with no single owner, not an addressed command.

### D5: Does a command wait for the app's handler to finish?

**Situation:** handlers can be long (`cameras_cast` runs up to its timeout and restarts on a second press).
hass-hassette's action timeout is 45 s; HA's UI shows a spinner until the service call returns.

**Deciding factor:** HA's UI stays responsive and errors land where someone will see them.

| | A: Return once dispatched | B: Wait for the handler |
|---|---|---|
| UI responsiveness | Immediate | Blocks up to the handler's runtime or the timeout |
| Handler exceptions | In hassette's handler telemetry and logs; not an HA toast | HA toast with the error |
| Delivery failures (hassette down, instance stopped, unknown entity) | HA toast | HA toast |
| Second press while running | Handled by the handler's own mode, like bus listeners | Second call blocks too |
| Peers | ESPHome, MQTT, Node-RED: fire and confirm via state | — |

**Recommendation:** A, because it matches every peer and keeps long handlers from tying up HA, while
delivery failures still surface in HA.
**Pick B instead if** you want handler exceptions shown in HA and your handlers are short.
**Reversibility:** easy.
**Ratified:** Chose returning once the command is dispatched over waiting for the handler, to keep HA's UI responsive for long handlers as every peer does, accepting that handler exceptions show in hassette's telemetry and logs rather than as an HA toast; delivery failures still error in HA. Challenge (Findings 6, 14): the command route accepts only a key its instance currently declares while that instance is `running`, and returns a typed conflict otherwise (reload and `starting` included); a press or toggle dropped or superseded by the handler's mode is recorded through the existing near-miss (drop) path with a log line. Accepted limitation: anyone holding hassette's web API token can press or toggle any declared entity. Re-challenge: the route's conflict codes (instance not running; key not declared by the instance) are part of the wire contract, each with its own `hassette-client` exception, and hass-hassette's action error table gains a row and translation for each.

### D6: Who is the source of truth for switch and sensor state, and how does it survive restarts?

**Situation:** #3993 requires switch state to survive both an HA and a hassette restart. Every maintained
peer with a confirmed switch treats the runtime as the switch's truth and doesn't use HA's RestoreEntity for it. hassette has a
database but no per-app key-value storage.

**Deciding factor:** after any restart, HA and the app agree on the switch without the app writing restore code.

| | A: hassette persists last state; app reads it on startup | B: App owns it, no persistence | C: HA restores it (RestoreEntity) and reports it to hassette |
|---|---|---|---|
| Survives hassette restart | Yes | Only if the app persists it itself | Yes, via a round trip at startup |
| Survives HA restart | Yes: integration re-reads from hassette | Yes, while hassette stays up | Yes |
| App boilerplate | None; the handle exposes the restored state | Every app writes its own persistence | None, but state arrives after HA connects |
| Truth while both run | hassette | hassette | Split: HA at startup, hassette after |
| New machinery | Entity-state table in hassette's DB | None | A HA → hassette restore message |
| Peers | Node-RED (runtime storage) | MQTT apps without retained state | Only MQTT's optimistic mode |

**Recommendation:** A, because it keeps one source of truth, meets the acceptance criterion with no app
code, and matches Node-RED. Sensors' last values go in the same table, so a sensor keeps its last value
across a hassette restart, as MQTT's retained state topics do (sensors going unknown after a restart is
Node-RED's most-reported bug class).
**Pick B instead if** you'd rather add no persistence and accept switches resetting on hassette restart.
**Pick C instead if** you want HA's restore to be the truth and accept a split source.
**Reversibility:** medium (a persisted table is a migration to remove).
**Ratified:** Chose hassette persisting each switch's last state in its database, exposed on the handle at startup, over app-owned state with no persistence or HA's RestoreEntity, to keep one source of truth that survives both restarts with no app code, accepting a new table. Reopened after the peer audit: sensors' last values are persisted in the same table too, so they survive a hassette restart like MQTT's retained state. Challenge (Findings 8, 10, 11): a never-set sensor is `unknown`, and a restored value carries no age, like MQTT retained state. An entity-state write is committed before the value appears in the listing or on `/ws`; a failed write leaves the in-memory and published value unchanged and raises from `set()` (the framework's post-handler write logs an error instead). State rows are keyed by `(app_key, instance_name, key, platform)` and a row is deleted in the same transaction that commits a running instance's declarations without that `(key, platform)` pair (D9), so a re-declared key never inherits old state; `platform` is in the row key so a key moved to another platform starts fresh too (HA sees it as a new entity on that platform). Attributes are persisted and restored with the value.

### D7: After a toggle, who changes the switch's state?

**Situation:** confirmed switches (ESPHome, MQTT with a state topic) change only when the runtime reports
a new state. NetDaemon's MQTT docs make the app set it in its command handler, which every app then repeats.

**Deciding factor:** the switch reflects what the app actually did, without boilerplate in each handler.

| | A: Framework sets it when the handler returns without error | B: Handler must set it | C: Optimistic: set before the handler runs |
|---|---|---|---|
| Boilerplate | None | One line in every handler | None |
| Handler fails | State unchanged | State unchanged | State wrong until corrected |
| Handler wants to refuse | Raise, or set the state itself (its value wins) | Don't set it | Must revert |
| Confirmed (peer practice) | Yes | Yes | No |

**Recommendation:** A, because it is confirmed like the peers but spares every handler the same line, and
a handler that sets the state itself still wins.
**Pick B instead if** you want switch state changes always explicit in app code. **Pick C instead if**
you want instant feedback and accept wrong state on failure.
**Reversibility:** easy.
**Ratified:** Chose the framework setting the switch state when the handler returns without error (a state the handler sets itself wins) over requiring every handler to set it or flipping it optimistically, to keep switches confirmed like the peers without per-handler boilerplate, accepting that a handler refusing a toggle must raise or set the state explicitly. Challenge (Finding 7) spelled out the rule: the framework sets the commanded value when the handler returns without error unless the handler called `set()` during that run; a handler that sets then raises keeps its own value; a cancelled run leaves state unchanged; under `parallel` mode the last-completed run wins; a long handler wanting immediate feedback calls `set()` first; the crash window between a handler's side effect and the state commit is accepted. Re-challenge: the docs page explains that HA's toggle shows the old state until a slow handler finishes, next to the `set()`-first advice.

### D8: When can an instance declare entities?

**Situation:** orphan removal (D9) needs each instance's full declaration list to be complete at a known
point. Listeners and jobs are registered in `on_initialize` by convention, but may be added later.

**Deciding factor:** the declaration list is complete and stable whenever the integration reads it.

| | A: Only during `on_initialize` | B: Any time while running |
|---|---|---|
| List complete when instance is running | Yes | No: a late declaration looks like an orphan until made |
| Dynamic sets (per-dog switches) | Fine when known from config at init | Fine |
| Error for a late declaration | Specific error at the call | n/a |
| Peers | ESPHome: list fixed per connect | Node-RED: any time |

**Recommendation:** A, because it makes "running" mean "list complete", which D9's removal relies on.
**Pick B instead if** you have apps that only learn their entities after startup, and accept a separate
"declarations complete" signal.
**Reversibility:** easy to loosen later.
**Ratified:** Chose declaring only during `on_initialize` (a later declaration raises a specific error) over declaring any time with an author-fired "declarations complete" signal, to make a running instance's list always complete for D9's removal, accepting that apps can't add entities after startup. The docs page carries a warning admonition stating this rule and the error, next to the first declaration example. If a late-declaring app appears, loosen it additively: the list is complete when `on_initialize` returns unless the app opts in to deferring and signals completion itself. Challenge (Finding 5): the same admonition warns that an app whose declarations depend on a lookup should let a failed lookup fail `on_initialize`, because a failed instance keeps its entities while a running instance with a short list loses them (D9).

### D9: When is an entity removed from Home Assistant, and what happens while its instance is down?

**Situation:** peers that remove only on an observed delete (Node-RED, NetDaemon) leave orphans forever;
ESPHome diffs a full list on every connect. hass-hassette already removes app devices only from a trusted
list (good poll, app startup released). An instance that fails before or during `on_initialize` hasn't
declared anything this run.

**Deciding factor:** no orphans, and no entity (with its history and user customizations) removed because
an instance is temporarily failing.

| | A: Diff running instances; keep the last declarations of down instances | B: Never auto-remove | C: Diff everything every poll |
|---|---|---|---|
| Removed declaration disappears | Yes, once the instance runs again | No; user deletes it | Yes |
| Failed or stopped instance | Keeps its last declared entities, unavailable | Same | Entities removed, history lost on every failure |
| Instance removed from config | Settled separately (D13) | Stay | Removed |
| Needs persisted declarations | Yes, per instance in hassette's DB | No | No |
| Peers | ESPHome; HA stale-devices rule | Node-RED, NetDaemon (documented orphan bugs) | — |

**Recommendation:** A, because it is ESPHome's diff gated on hassette's own "running" signal plus the
trusted-list gate hass-hassette already uses, so a failure never deletes entities.
**Pick B instead if** you'd rather never delete anything automatically and accept manual cleanup.
**Reversibility:** easy.
**Ratified:** Chose diffing only running instances' declarations (behind the existing trusted-list gate) while down instances keep their last persisted declarations as unavailable entities, over never auto-removing or diffing every poll, so no orphans remain and no failure deletes entities, accepting per-instance declarations persisted in hassette's database. Challenge (Findings 4, 12, 13): declarations are collected in memory during `on_initialize` and replace the instance's persisted set in one transaction when it reaches `running`, so a failed or half-finished init never touches the persisted set. A `set()` during `on_initialize` is held with the pending declarations and written in that same commit. A declared entity is available only while its instance's status is `running` and the trusted-list gate holds; `starting`, `stopping`, `stopped` and `failed` show unavailable, and the integration never diffs a non-running instance. Accepted limitation: the integration infers a complete list from `running`, which is exact given the single commit. Accepted limitation (re-challenge): pushed `app_status_changed` carries no revision, so a stale poll can briefly show a stopping instance's entities available until the next poll or push; a press in that window gets D5's conflict.

### D10: What happens when an app declares entities without the integration?

**Situation:** #3993 asked for declaring without hass-hassette to fail with a specific error. The
integration connects to hassette, not the other way round, so hassette can only learn it is installed by
asking HA (a `hassette` config entry). No peer raises: NetDaemon's MQTT manager doesn't check, its old
integration failed only incidentally (missing service), and Node-RED shows a passive "integration not
loaded" node status.

**Deciding factor:** match peers' weight for a failure that is obvious anyway (the entities never appear).

| | A: Check HA config entries and raise | D: No check; document the requirement | E: No raise; one warning per run if no config entry |
|---|---|---|---|
| Peers | None raise | NetDaemon MQTT | Closest to Node-RED's status |
| App fails over a missing integration | Yes | No | No |
| What the user sees | An error in hassette | Entities never appear in HA | One warning line in hassette's log |
| New machinery | One HA WS call, cached per run | None | Same call as A |
| #3993 acceptance criterion | Kept | Dropped | Softened to a warning |

**Recommendation:** D, because peers either don't check or only show a passive status, and the docs
page's setup section can state the requirement up front.
**Pick E instead if** you want some signal in hassette. **Pick A instead if** you want #3993's criterion as written.
**Reversibility:** easy (a check can be added later).
**Ratified:** Chose no installation check, with the docs stating up front that hass-hassette is required, over raising at declaration or logging a warning, to match peers and add no machinery, accepting that a missing integration shows only as entities never appearing in HA; #3993's error criterion is dropped.

### D11: What are the unique_id, device identifier and entity key formats?

**Situation:** v0.1 uses `{app_key}-{key}` unique_ids and `(hassette, app_key)` device identifiers,
relying on `-` being outside the `app_key` alphabet. `instance_name` is required, lowercase letters,
digits and `_`, so it has no `-` either. Entity keys are new.

**Deciding factor:** unambiguous forever, no collision with v0.1's framework entities.

**Recommendation:** unique_id `{app_key}-{instance_name}-{key}`; instance device identifier
`(hassette, "{app_key}-{instance_name}")`; entity keys use the `instance_name` rule (lowercase, digits,
`_`), validated at declaration, unique per instance. Three segments never collide with v0.1's two, and
renaming an app key, instance or entity key makes a new entity, as v0.1 already accepts for app keys.
**Pick something else if** you want entity keys to allow `-` or mixed case (then the segment must be encoded).
**Reversibility:** hard (unique_ids are a one-way door). Collapsed despite that: it extends hass-hassette v0.1's ratified unique_id scheme (its D5), which already chose `-` separators for exactly this extra segment.
**Ratified:** Chose `{app_key}-{instance_name}-{key}` unique_ids, `(hassette, "{app_key}-{instance_name}")` instance device identifiers, and entity keys under the `instance_name` rule validated unique per instance, over richer encoded keys, to stay unambiguous and collision-free with v0.1's two-segment ids, accepting that renaming any segment creates a new entity.

### D12: What does declaring an entity look like in app code?

**Situation:** hassette's bus and scheduler register imperatively in `on_initialize` with awaited calls
and a required `name=`. NetDaemon's entity manager is imperative with returned handles. A class-level
declarative form would list entities without running the app, but can't use per-instance config.

**Deciding factor:** consistent with how apps already register listeners and jobs.

| | A: Imperative, awaited, returns a handle | B: Declarative class attributes |
|---|---|---|
| Example | `self.show = await self.integration.add_button("show_cameras", name="Show cameras", on_press=self.on_show)` | `show = AppButton("show_cameras", on_press="on_show")` |
| Per-instance config (names, per-dog keys) | Yes | No, or awkwardly |
| Consistent with bus/scheduler | Yes | No |
| State updates | `await self.sensor.set(value, attributes=...)` on the handle | Same, via the attribute |
| Handler wiring | Bound method, same invocation machinery as listeners | String or descriptor lookup |

**Recommendation:** A, because it matches how apps already register everything else and handles
per-instance config naturally. Handles expose `set` for sensors and switches and the current (restored)
state; handler parameters follow the framework's "only what the signature declares" rule.
**Pick B instead if** listing entities without starting the app matters more than per-instance config.
**Reversibility:** easy now, hard after release.
**Ratified:** Chose imperative, awaited `add_*` calls in `on_initialize` returning handles (with `set` and the restored state) over declarative class attributes, to match how apps register listeners and jobs and to use per-instance config, accepting that entities can't be listed without starting the app. Handle type names are settled in the building issue, without reusing `*Entity` names (D2). Comb follow-up, following HA's sensor and switch conventions: `set()` rejects a value of the wrong type for the sensor's declaration (rule below); a newly declared switch starts off unless the declaration passes an initial value; a switch handler receives the commanded value (on or off). `add_*` takes the bus's execution-mode option for its handler, with the bus's default (`single`), so a long handler such as `cameras_cast`'s opts into `restart` the same way its listener does today. A sensor's value type follows HA's rules for its declared device class, unit and state class: numeric where HA requires a number, otherwise the type HA expects for that class (a string by default). Re-challenge: on the wire a value is a JSON scalar (`int | float | str | bool`) or `null` for unknown; hassette owns the type table (from its pinned HA) and enforces it in `set()`; attributes are JSON-serializable; the integration passes values through and leaves any rejection to HA's log. A declaration may carry an optional suggested entity id, which the integration applies only when it first creates the entity (MQTT's `default_entity_id`, NetDaemon's overridable id); the docs say HA otherwise assigns the entity_id from device and entity name, so migrating a shared helper means updating its consumers.

### D13: What happens to an instance removed from config?

**Situation:** D9 keeps a down instance's entities and diffs only running ones, so an instance deleted
from config would keep its device, entities and persisted rows forever. hass-hassette v0.1 already
settled this for apps (its D16): it never auto-removes an app device; it lets the user delete one once
hassette reports the app not in current config, because a saved config edit flips that flag on the next
poll. Instances carry the same `in_current_config` flag (Assumed). Peers: HA's stale-devices rule allows
user-initiated removal; portainer (v0.1's reference) and ESPHome never auto-remove a whole unit; Node-RED
never removes.

**Deciding factor:** a removed instance can be cleaned up without risking data loss from a config edit or typo.

| | A: v0.1's rule; hassette prunes rows at startup | B: Auto-remove when the instance leaves config | C: Do nothing |
|---|---|---|---|
| HA device and entities | User may delete the instance device once the instance isn't in current config; never auto-deleted | Integration removes them on the next trusted poll | Stay unavailable until removed by hand |
| hassette's persisted rows | Deleted at startup for instances absent from the loaded config | Deleted at config load | Kept forever |
| Config typo or commented-out instance mid-run | Safe until the next restart | Loses entities, history and switch state | Safe |
| Matches existing behavior | Yes, v0.1's app-device rule | No | No |
| New machinery | Startup pruning | Config-load pruning and integration-side removal | None |
| Peers | HA stale-devices (user-initiated), portainer, ESPHome | ESPHome's per-entity diff, applied to units | Node-RED |

**Recommendation:** A, because it reuses v0.1's peer-backed rule for the HA side and prunes hassette's rows
only at startup, never on a mid-run config edit.
**Pick B instead if** you want no manual cleanup and accept losing state to a config mistake. **Pick C
instead if** removed instances are rare enough that leftover rows don't matter.
**Reversibility:** easy.
**Ratified:** Chose v0.1's user-initiated device removal for instances no longer in current config, with hassette deleting an absent instance's persisted declarations, and state at startup (absent: hassette's config has no entry for its `app_key`, or its `instance_name` is not among that app's configured instances; an app that is disabled, filtered out by `--app`, or not autostarted is not absent), over auto-removal or keeping everything, so no config edit deletes anything on a guess, accepting that a removed instance's device stays until the user deletes it. The listing reports a removed instance with `in_current_config` false until the startup prune, after which it is absent; the integration treats absent and not-current alike as removable, as v0.1 does for apps.

### D14: Why integration entities rather than code-created helpers or MQTT discovery?

**Situation:** hassette's `Api.helpers` already creates and updates `input_button`, `input_boolean` and
`input_number` helpers from code (the corpus's monarch app self-provisions about 25 that way), and
NetDaemon moved its entity support to MQTT discovery. The milestone needs to say what it adds over both.

**Deciding factor:** state why the milestone exists without reopening D1–D13.

**Recommendation:** keep integration-backed entities. Over code-created helpers they give: a press while
hassette is down errors in HA instead of changing a helper nobody hears; switches are confirmed instead of
flipping whether or not the app acted; sensors are read-only with unit, device and state class (so
long-term statistics), where `input_number` is user-editable with neither; entities group under a
placeable instance device; removed declarations are removed. Code-created helpers stay the route for an
app that must work without hass-hassette. MQTT discovery isn't used: it needs a broker and an MQTT client
hassette doesn't have, nothing sweeps retained declarations that drop out of code, and hass-hassette is
already installed and owns the framework entities this extends.
**Pick something else if** the confirmed-switch and lost-press gains don't matter, and sensors alone justify the work.
**Reversibility:** easy now.
**Ratified:** Chose integration-backed entities over code-created helpers or MQTT discovery, to fix lost presses and unconfirmed switches and give real sensors while reusing hass-hassette, accepting that declared entities need the integration installed (D10).

## Assumed

- hass-hassette connects out to hassette's web API and polls `/api/health` and `/api/apps`; it never
  receives inbound connections from hassette. Evidence: hass-hassette `HassetteCoordinator`; ADR-0006 and the
  August 2026 integration-transport-revisit research brief.
- `app_key` excludes `-` (letters, digits, `_` and `.`), which v0.1's identifiers rely on. Evidence:
  hassette's web API app-key validation, mirrored as `APP_KEY_PATTERN` in hass-hassette's coordinator.
- `instance_name` is required and matches lowercase letters, digits and `_`, so `-` can't appear in it.
  Evidence: `resolve_instance_name` / `instance_name_reason` in hassette's app config classes.
- v0.1 unique_ids `{app_key}-{key}`, app device identifiers and the hub identifier are fixed public
  surface, and the framework entity keys in them (`switch`, `reload`, `status`) contain no `-`. Evidence:
  hass-hassette spec 001 D5; hass-hassette CLAUDE.md conventions; its entity descriptions.
- hassette's `/ws` already sends `app_status_changed` when an instance's status changes. Evidence:
  `hassette_wire` `AppStatusChangedWsMessage`.
- Each `AppInstance` in the app listing carries `in_current_config`, false for an instance still tracked outside the
  app's config. Evidence: `hassette_wire` `AppInstance`.
- hassette's web API already accepts per-instance targets for app actions. Evidence: `HassetteClient.action(..., instance=)`.
- hass-hassette removes app devices only from a trusted list (good poll and bootstrap released). Evidence:
  `HassetteCoordinator.app_list_trusted`, `async_remove_config_entry_device`.
- Every new app-facing API must be testable through the app-testing harness. Evidence: hassette CLAUDE.md, "Designing the Framework".
- The released `hassette-client` must keep parsing every response newer hassette sends. Evidence: `nox -s client_compat`.

## Breakdown

**Done when:** an app instance can declare a button, switch and sensor in `on_initialize`; each appears
in HA under the instance's place in the device model with a stable unique_id; pressing or toggling runs
the instance's handler with standard telemetry; app-set state reaches HA; switch state survives an HA and
a hassette restart and a sensor keeps its last value across a hassette restart; a stopped instance's entities are unavailable and a removed declaration's entity is
removed; a removed instance's device can be deleted in HA and its rows are pruned at the next start; the
monitoring UI shows each instance's declared entities; it
is all testable through the
harness and covered by an end-to-end system test with hass-hassette loaded in HA; and the docs page and
hass-hassette README describe it, including that hass-hassette is required.

Applies to issues 2, 3 and 5: D11 (identifier formats), D2 (naming).

1. **Extend the wire-compatibility check to WebSocket payloads**: the existing #2439 scope, so a breaking
   `/ws` change can't ship before the integration starts parsing it. Implements: prerequisite for D3.
   After: none. Issue: #2439
2. **hassette: app instances declare buttons, switches and sensors**: the `self.integration` resource and
   its handles; declarations only in `on_initialize` with a specific error otherwise; key validation;
   persisted per-instance declarations and last switch and sensor state with the running-time commit;
   the framework setting a switch's state after its handler succeeds; sensor declarations carrying unit,
   device class and state class with `set()` enforcing D12's value types; the optional suggested entity
   id; handler registration with the bus's execution mode and near-miss recording for dropped or
   superseded presses; the revision counter and boot identifier, bumped on state change and declaration
   commit; pruning absent instances' rows at startup; harness support (declarations visible to tests,
   simulated presses and toggles); the docs page, with the `on_initialize`-only warning admonition (and
   D8's lookup-failure warning), the slow-handler snap-back note, the entity_id note, when to use code-created
   helpers instead (D14) and the hass-hassette requirement. Implements: D2, D6, D7, D8, D9 (hassette side), D10, D12, D13 (hassette
   side), D14. After: none. Issue: #4218
3. **hassette: serve declared entities over the web API**: the new `hassette_wire` models; each instance's
   declarations and state with the revision (D3) in the app listing; the command route with its
   conflict codes, dispatching to the owning instance's handler and returning once dispatched; the
   `hassette-client` command method and its exceptions, with the API schema floor bump (Posture); the
   monitoring UI showing each instance's declared entities; regenerated schemas and frontend types; the
   route wired into issue 2's dispatch. Implements: D3 (revision), D4, D5. After: 2.
   Issue: #4219
4. **hassette: stream entity state over `/ws`, and give `hassette-client` WebSocket subscriptions**: entity
   state messages on `/ws` carrying the revision (D3) (declaration changes reach the integration through the listing, which D9's diff already reads); a client subscription API
   that subscribes before it fetches the REST listing on every (re)connect and skips message types it
   doesn't know (debug log); regenerated frontend types. Implements: D3. After: 1, 3. Issue: #4220
5. **hass-hassette: create app-declared entities**: instance devices on demand under app devices; button,
   switch and sensor entities from the polled listing, with the suggested entity id applied on first
   creation and the instance device named from its `instance_name` (formatting settled in this issue's
   sketch); availability tied to the instance running; commands through the new route, with the action
   error table extended for its conflict codes; the running-instance diff behind the trusted-list gate;
   polled entity state applied only when its revision is newer; user-initiated removal of an instance
   device once its instance isn't in current config. Implements: D1, D3 (revision), D4, D5, D9
   (integration side), D12 (entity id), D13 (integration side). After: 3 (released). Issue: NodeJSmith/hass-hassette#72
6. **hass-hassette: push entity state from hassette's `/ws`**: subscribe through `hassette-client`, apply
   pushed state, apply the existing `app_status_changed` message to availability (D9), and resync from
   the REST listing on every (re)connect so a dropped stream degrades to polling. Implements: D3, D9
   (availability). After: 4 (released), 5. Issue: NodeJSmith/hass-hassette#73
7. **End-to-end: app-declared entities against a real HA**: load hass-hassette into hassette's system-test
   HA container and cover declare → entity in HA → press/toggle → handler → state in HA, plus both
   restarts and a removed declaration; update hass-hassette's README. Implements: verifies D1, D3, D6, D9.
   After: 5, 6. Issue: #4221

Closes: #3993, when all seven land. Each "(released)" gate means a hassette release and a hass-hassette
client pin bump; whether issues 3 and 4 share a release is settled at release time (accepted). #1449 is not in the milestone; D2 settles only its name.
Related, outside the milestone: #4217 (close slow `/ws` clients instead of dropping their messages); D3's
poll and revision bound a dropped message without it.

## Addendum

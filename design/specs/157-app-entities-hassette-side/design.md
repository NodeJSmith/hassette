# Design: App instances declare Home Assistant buttons, switches and sensors (hassette side)

**Date:** 2026-11-19
**Status:** built
**Mode:** sketch
**Issues:** #4218
**Parent:** design/specs/155-hacs-app-entities/design.md
**Prior art:** design/research/2026-11-16-app-declared-ha-entities/prior-art.md

## Summary

Breakdown item 2 of the HACS App Entities milestone. An app instance declares buttons, switches and
sensors in `on_initialize` through `self.integration`. hassette persists each instance's declarations
and its last switch and sensor state, and runs the owning handler when a press or toggle is dispatched.
This issue is everything on the hassette side short of serving it: the web API listing, the command
route, the `hassette_wire` models and the monitoring UI belong to #4219, which calls this issue's
in-process dispatch entry point. The `/ws` stream is #4220. hass-hassette is #72/#73.

Where each new piece lives:

- **`self.integration`**: a new per-instance child resource on `App` (`src/hassette/integration/`,
  a package beside `bus/` and `scheduler/`), added in `App.__init__` with `add_child` and listed in
  `_APP_PUBLIC_API` (`src/hassette/app/app.py`). It holds the instance's pending declarations and
  pending `set()` values until the running-time commit, then the committed handles. Sync apps get a
  `self.integration.sync` facade, following `BusSyncFacade`.
- **Handles**: one class per platform in the same package, named by D2, returned by `add_button`,
  `add_switch`, `add_sensor`. Signatures (all keyword after `key`):
  `add_button(key, *, name, on_press, mode=<bus default>, default_entity_id=None)`;
  `add_switch(key, *, name, on_toggle, initial=False, mode=<bus default>, default_entity_id=None)`;
  `add_sensor(key, *, name, unit=None, device_class=None, state_class=None, options=None,
  default_entity_id=None)`. `mode` takes the bus's `ExecutionMode`. An invalid or duplicate key, an
  invalid `default_entity_id` (D6) or an invalid sensor declaration (D5) raises `ValueError` at the call.
  Switch and sensor handles expose `set()` (D13) and the current (restored) state. The
  `self.integration.sync` facade covers the three `add_*` calls and each handle's `set()`, as
  `BusSyncFacade` does for the bus.
  `set()` on a handle whose owning `self.integration` resource has shut down raises
  `IntegrationHandleClosedError` (a `HassetteError`) naming the instance, checked against that resource's lifecycle status, so a task leaked past a reload
  can't overwrite the new instance's row.
- **Core service**: a new `Service` in `src/hassette/core/` holding every instance's committed
  declarations and entity state in memory, backed by the database; the per-boot identifier and the
  hassette-wide revision counter (parent D3); the running-time commit; `set()` writes; the startup
  prune (parent D13); and the dispatch entry point #4219's route calls. It depends on
  `DatabaseService` like `BusService` does, and `AppBootstrapCoordinator.depends_on` gains it, so it
  has pruned and loaded before any instance can commit. How its memory follows the database is D10.
- **Persistence**: a new migration `src/hassette/migrations_sql/027.sql` (shape is D4), written
  through `DatabaseService.submit()` so every write is awaited and raises. The write connection
  autocommits (`isolation_level=None`), so the replace-set commit (the upserts and the removed-declaration
  row deletes) runs as `SQL_BEGIN` … commit inside `try/except BaseException: safe_rollback(...); raise`,
  following `src/hassette/core/database_retention.py`; a failure between the upsert and the delete
  leaves the old set intact. Values are stored as JSON: a timestamp sensor's value as an ISO 8601 string
  with offset, a date sensor's as an ISO 8601 date. On load they are parsed back to the types D5 gives
  the handle, and D12's check runs on the parsed value, so an unchanged declaration keeps its value
  across a restart. A switch's `initial` is written into the value column when the commit inserts its
  row, so `NULL` means `unknown` for a sensor only; changing `initial=` later has no effect on a row
  that already exists. The table is never a retention or size-failsafe
  target (`src/hassette/core/retention_targets.py`): it holds the only copy of switch and sensor state.
- **Commit point**: `AppLifecycleInstances.initialize_instance`
  (`src/hassette/core/app_lifecycle_instances.py`), after `inst.initialize()` returns and outside its
  startup-timeout block, before the `RUNNING` status write; admission and stop behavior around it are
  D10. `outcomes.succeeded` and the "initialized successfully" log move after the commit.
- **Dispatch**: D1. Each `add_button`/`add_switch` registers its listener on the app's own `self.bus`
  at the call, with a predicate matching its app key, instance name, key and platform, so the app's
  bus teardown removes it and a failed init leaves no listener behind.
- **Startup prune**: runs once in the core service's startup step, using the loaded config, before the
  service loads declarations and state into memory, so memory is loaded from the pruned database. It
  does not sit behind `bootstrap_apps`' empty-manifests early return, and a prune failure fails the
  service's startup. Accepted limitation: a restart with an empty or
  wrong apps config prunes every instance's declarations and switch and sensor state, as parent D13
  already accepts for a config mistake; each pruned instance is logged (Posture, Hardening).
- **Harness**: `AppTestHarness` (`src/hassette/testing/`) gains `simulate_button_press` and
  `simulate_switch_toggle` beside the existing `simulate_*` methods, and exposes the instance's
  declarations and entity state. The harness runs no `DatabaseService`, so it backs the core service
  with an in-memory store that keeps the same commit and `set()` semantics. That store never fails, and
  the harness offers no way to make a write fail; the commit, cancel and failed-`set()` behavior (D10)
  holds against the real `DatabaseService`.
- **Docs**: D9. The "Safe to delete" paragraph in `docs/pages/troubleshooting.md` and the D9 page both
  say that deleting `hassette.db` also resets declared switch and sensor values (declarations come back
  at the next start). The page's handler examples follow D11.

Out of scope: everything #4219, #4220 and the hass-hassette issues own; platforms other than button,
switch and sensor; entity icons, categories and availability overrides.

## Posture

- **Failure handling:** loud failure. A failed running-time commit fails the instance's init (it goes
  `FAILED` and keeps its last persisted declarations, parent D9). `set()` raises on a failed write.
  No retries or queuing.
- **Compatibility:** hassette's Python API may break freely (pre-V1). The new table is an additive
  migration. No wire model changes in this issue (#4219 adds them).
- **Scope:** minimal: exactly Breakdown item 2 of the parent. The web API, wire models, command route
  and monitoring UI are #4219.
- **Rollout:** ships outright, no flag. Nothing consumes the feature until #4219 and hass-hassette ship.
- **Hardening:** project defaults. Handlers get the standard handler telemetry and error isolation.
  Log points, with structured fields via `extra=`: INFO for each running-time commit (instance; counts
  added, kept, removed); WARNING for each pruned `(app_key, instance_name)` with row counts; WARNING when
  the dispatch entry point rejects a press (`not_running`, `not_declared`); a press dropped by the
  handler's mode is logged at DEBUG by the existing guard (`ExecutionModeGuard`, `src/hassette/execution_mode.py`)
  alongside its near-miss record; WARNING for each restored
  value reset by D12; ERROR (via `exception()`) for a failed running-time commit, before the failed-init
  path.
- **Altitude:** build; one session builds it.

## Decisions

### D1: How does a dispatched press or toggle reach the app's handler?

**Situation:** parent D5 and D12 require handlers to run with the bus's execution modes (default
`single`, `restart` for `cameras_cast`), standard handler telemetry, and near-miss recording when a
press is dropped or superseded by the mode. The bus already does all of that for listeners:
`HandlerInvoker.run_with_mode` (`src/hassette/bus/invoker.py`) applies the `ExecutionModeGuard`,
`Delivery.drop` records `busy`/`queue_full` near-misses through the listener's `DropReporter`, and
`CommandExecutor` records each invocation against the listener's DB row. Handler telemetry tables are
keyed by listener or job, and the near-miss path is bound per listener. Internal events already travel
the bus on `hassette.event.*` topics (`Topic` in `src/hassette/types/enums.py`).

**Deciding factor:** presses and toggles get the same modes, telemetry and near-miss records as
listeners, without a second copy of that machinery.

| | A: Each declaration registers a bus listener on a new internal command topic | B: A dedicated invoker in the integration resource, like the scheduler's |
|---|---|---|
| Execution modes | The listener's existing guard | Reuse `ExecutionModeGuard` directly; new wiring |
| Handler telemetry | Existing listener rows and invocation records | A new owner kind beside listener and job: schema, wire and UI changes |
| Near-miss on drop | Existing `busy`/`queue_full` reasons, no wire change | New reporter path; `DropReporter` is listener-scoped |
| DI, `on_error`, timeouts | Existing | Re-plumbed |
| Visible in the monitoring UI today | Yes: each declaration's listener shows in the app's listeners view | Not until #4219 |
| Side effect | The command event is visible on the bus to any listener | None |
| Peers | NetDaemon's MQTT entity manager hands commands to the app as an `IObservable<string>`, the same model as its HA events | ESPHome: per-entity C++ callbacks on the device |

**Recommendation:** A, because every behavior the parent asks of a handler already exists on a bus
listener, and it puts declared handlers in the listeners view now. The listener's name is generated
from the declaration (`integration.<platform>.<key>`, unique per instance by parent D11), so no `name=`
is asked of the app. The topic is `Topic.HASSETTE_EVENT_INTEGRATION_COMMAND` (`"hassette.event.integration_command"`)
and the event `IntegrationCommandEvent`, carrying app key, instance name, key, platform and, for a
switch, the commanded value. The handler is registered as is, with no wrapper (D11).

The dispatch entry point #4219's route calls: it checks that the instance's
registry status is `running` and that the key is in its committed declarations, then publishes the
command event with no await between the checks and the publish, and returns a typed result:
`dispatched`, `not_running` or `not_declared` (parent D5's conflicts). `dispatched` means published,
not ran: a `single` or `queued` drop shows only as a `busy` or `queue_full` near-miss record, and a
`restart` supersession as the superseded run's `cancelled` invocation record. Declaration listeners use
`BLOCK` backpressure.
**Pick B instead if** you don't want app-declared commands visible as bus events, and accept new
telemetry and near-miss plumbing plus its UI.
**Reversibility:** easy before release (internal); the topic name becomes visible on the bus once shipped.
**Ratified:** Chose registering each declaration's handler as a bus listener on a new internal command topic over a dedicated scheduler-style invoker, to reuse the listener's execution modes, handler telemetry, near-miss records and listeners-view visibility, accepting command events visible on the bus. The sketch challenge added the entry point's contract above: running and declared checks with no await before the publish, a typed `dispatched`/`not_running`/`not_declared` result where `dispatched` means published, and `BLOCK` backpressure. Accepted limitation: any app can publish the internal command topic and run another app's declared handler, bypassing those checks, as MQTT and NetDaemon command topics allow and parent D5 already accepts through the web API token.

### D2: What are the handle types called?

**Situation:** parent D2 rules out `*Entity` names (`SwitchEntity` already means a reference to an HA
entity) and leaves the names to this issue. hassette names its other registration results for what
they are: `Subscription` (bus), `ScheduledJob` (scheduler). App code annotates them
(`self.show: <Type>`), and they're exported from `hassette`.

**Deciding factor:** reads unambiguously in app code, next to `SwitchState` and `SwitchEntity`.

| | A: `IntegrationButton`, `IntegrationSwitch`, `IntegrationSensor` | B: `ButtonHandle`, `SwitchHandle`, `SensorHandle` | C: `Button`, `Switch`, `Sensor` |
|---|---|---|---|
| Distinct from `SwitchState`/`SwitchEntity` | Yes, and names the dependency | Yes | Weak: reads as "a switch", which `SwitchEntity` already is |
| Matches `self.integration.add_switch(...)` | Yes | Neutral | Neutral |
| Matches `Subscription`/`ScheduledJob` (name what it is) | Yes | No: names the mechanism | Yes |
| Length | Long | Medium | Short |
| Peers | NetDaemon, AppDaemon: no handle types; n/a | n/a | n/a |

**Recommendation:** A, because it can't be mistaken for a reference to any HA switch and repeats the
attribute it came from.
**Pick B instead if** you prefer shorter names and don't mind the `Handle` suffix. **Pick C instead
if** brevity outweighs the overlap with `SwitchEntity`.
**Reversibility:** easy now; a user-facing rename after release.
**Ratified:** Chose `IntegrationButton`, `IntegrationSwitch` and `IntegrationSensor` over `*Handle` or bare `Button`/`Switch`/`Sensor` names, to read unambiguously next to `SwitchState`/`SwitchEntity` and echo `self.integration`, accepting longer names.

### D3: How does a switch handler receive the commanded value?

**Situation:** parent D12 says a switch handler receives the commanded value (on or off), and the
framework rule is that handlers get only the parameters their signature declares. hassette's injector
fills parameters from annotations (`D.MessageData[T]` is the latest example,
`src/hassette/event_handling/dependencies.py`). Under D1-A the value travels in the command event's
payload.

**Deciding factor:** a toggle handler reads the value with no boilerplate, the way other handlers get
their data.

| | A: A dependency annotation, `on: D.SwitchCommand` → `bool` | B: The typed command event, `event: IntegrationCommandEvent`, read `event.payload.data.value` | C: Inject by parameter name (`value`) |
|---|---|---|---|
| Boilerplate | None | One attribute path | None |
| Follows the injector's conventions | Yes | Yes | No: the injector works by annotation |
| Works with D1-A | Yes (an extractor over the event) | Yes, free | Needs a special case |
| Handler may ignore the value | Yes, by not declaring it | Yes | Yes |
| Peers | ESPHome `write_state(bool)` | NetDaemon: the raw `"ON"`/`"OFF"` string from the command observable | — |

**Recommendation:** A, because it reads like `D.MessageData` and gives a plain `bool`; B still works
for a handler that wants the whole event, since the command is an ordinary bus event under D1-A.
Button handlers take no value.
**Pick B instead if** you'd rather not add a dependency and accept the attribute path. **Pick C
instead if** you want the shortest handler signature and accept a name-based special case.
**Reversibility:** easy now.
**Ratified:** Chose a `D.SwitchCommand` dependency annotation that injects the commanded `bool` (the typed command event stays declarable too) over reading the event payload by hand or injecting by parameter name, to give toggle handlers the value with no boilerplate under the injector's annotation convention, accepting one new dependency.

### D4: What shape does the persisted data take?

**Situation:** parent D6 keys state by `(app_key, instance_name, key, platform)`, deletes a state row
in the same transaction that commits a running instance's declarations without that pair, and persists
attributes with the value. Parent D9 replaces an instance's whole declaration set in one transaction at
`running`. Fields differ by platform: all have a name and an optional suggested entity id (D6);
sensors add unit, device class, state class and, for enum sensors, options (D5); switches add an
initial value. Values on the wire are a JSON scalar or `null` (parent D12). #4219 reads this to build
the listing.

**Deciding factor:** D6's and D9's transactional rules fall out of the schema rather than being
enforced in code.

| | A: One table, one row per declared entity, typed columns for every field (platform-specific ones nullable), value and attributes as JSON | B: Two tables, declarations and state, state referencing its declaration | C: One table, identity columns plus a JSON `spec` for the declaration |
|---|---|---|---|
| D6 "removed declaration deletes its state" | The same row delete | `ON DELETE CASCADE` | The same row delete |
| D9 replace-the-set commit | Upsert kept rows (keeping state), delete the rest | Same, across two tables | Same as A |
| A re-declared key keeps state across restarts | Yes: the row's state survives the upsert | Yes | Yes |
| Queryable for #4219 and migrations | Yes | Yes | Platform fields only through JSON |
| Schema churn when a field is added | A column per field | A column per field | None |
| Peers | ESPHome persists the entity list per device in one store; Node-RED keeps node state in its context store | — | — |

**Recommendation:** A, because declaration and state share the exact key D6 names, so one row per
entity makes "removed declaration, removed state" a single delete and needs no join for #4219. A
missing state is a `NULL` value, which parent D6 already defines as `unknown`.
**Pick B instead if** you expect state to grow fields of its own (history, timestamps) and want it
separate. **Pick C instead if** you expect frequent new declaration fields and accept JSON queries.
**Reversibility:** medium (a migration to change).
**Ratified:** Chose one table with one row per declared entity, typed columns (platform-specific ones nullable) and the value and attributes as JSON, over separate declaration and state tables or a JSON declaration spec, so D6's "removed declaration, removed state" is one row delete and #4219 reads it without a join, accepting a migration per new declaration field.

### D5: Which sensor value types does `set()` accept?

**Situation:** parent D12 makes hassette own the sensor type table from its pinned HA and enforce it
in `set()`. `classify_sensor_shape` (`src/hassette/models/states/sensor_shapes.py`) already maps a
device class, unit and state class to `numeric`, `enum`, `timestamp`, `date` or `unknown`, over
`DEVICE_CLASS` generated from HA core (`src/hassette/const/sensor.py`). HA's `SensorEntity` itself
rejects a non-number for a numeric sensor, requires `options` for an enum sensor and a value from
them, and requires a timezone-aware datetime for a timestamp sensor.

**Deciding factor:** a wrong value fails in the app at `set()`, the way HA would fail it, with the
least new table code.

| | A: Follow HA through `classify_sensor_shape`: numeric, enum (with required `options`), timestamp, date, else string | B: Numeric or string only; reject the enum, timestamp and date device classes at declaration |
|---|---|---|
| Matches HA's own validation | Yes | For what it allows |
| New code | A shape → accepted-type map and an `options` parameter | A smaller map, plus a rejection list |
| Device classes usable | All of HA's | All but four |
| Unknown device class string | Rejected at declaration (HA would ignore it) | Same |
| Timestamp value | A `whenever` aware type, sent as ISO 8601 | n/a |
| Peers | HA `SensorEntity`; MQTT sensors pass any string and HA validates | NetDaemon passes strings and leaves validation to HA |

**Recommendation:** A, because the classifier already exists, so supporting every device class costs
one map and an `options` parameter, and an author gets HA's rule at `set()` instead of in HA's log.
Numeric means `int` or `float`, never `bool`. A timestamp `set()` accepts any aware `whenever` type and
normalizes it to `whenever.Instant`, so the handle exposes an `Instant` before and after a restart; a
date is a `whenever.Date`. `set(None)` returns a sensor to `unknown`. A switch accepts only `bool`. An
invalid value raises `ValueError` from `set()`.
**Pick B instead if** you want the smallest first cut and accept that enum, timestamp and date sensors
wait for a later issue.
**Reversibility:** easy (A → B narrows; B → A adds).
**Ratified:** Chose following HA's sensor rules through `classify_sensor_shape` (numeric, enum with required `options`, timestamp, date, else string) over allowing only numeric or string sensors, to fail a wrong value at `set()` the way HA would for every device class, accepting a shape-to-type map and an `options` parameter.

### D6: What does the suggested entity id look like?

**Situation:** parent D12 allows an optional suggested entity id that hass-hassette applies only when
it first creates the entity, after MQTT's `default_entity_id` (a full entity id, which replaced MQTT's
`object_id` in HA 2026.4). #4219 serves it in the listing, so it's persisted with the declaration.

**Deciding factor:** the name says "first creation only", and the value is checked where the author
writes it.

**Recommendation:** a `default_entity_id=` keyword taking a full entity id (`"sensor.kitchen_temp"`),
validated at declaration: its domain must match the platform, and its object id must be lowercase
letters, digits and `_`. Persisted in the declaration row. The name matches MQTT's current term, so
users who know MQTT discovery recognize it.
**Pick an object id only (`object_id="kitchen_temp"`) if** you'd rather not repeat the domain, and
accept MQTT's deprecated form. **Pick `entity_id=` if** you want the shortest name, and accept that it
reads as enforced.
**Reversibility:** easy now.
**Ratified:** Chose a `default_entity_id=` keyword taking a full entity id, validated at declaration (domain matches the platform, object id lowercase letters, digits and `_`) and persisted with the declaration, over an object-id-only form or an `entity_id=` name, to match MQTT's current term and signal "first creation only", accepting that the author repeats the domain.

### D7: When does the declaration window close, and what does a late call raise?

**Situation:** parent D8 allows declarations only during `on_initialize`, with a specific error
otherwise. The commit runs in `initialize_instance` after `inst.initialize()` returns, which runs
`before_initialize`, `on_initialize` and `after_initialize` (`Resource._initialize_body`,
`src/hassette/resources/base.py`). A task the app spawns during init may still be running after the
commit.

**Deciding factor:** the rule is checkable from one piece of state and can't let a declaration miss
the commit.

| | A: Open from instance creation until the commit; any later `add_*` raises | B: Open only while the `on_initialize` hook itself runs |
|---|---|---|
| Declaration in `before_`/`after_initialize` | Allowed | Raises |
| Spawned task declaring after the commit | Raises | Raises |
| Spawned task declaring during init | Allowed | Allowed only while `on_initialize` is on the stack |
| State the check needs | "snapshot taken yet?" on the resource | A flag set around one hook call |
| Can a declaration miss the commit | No: the window closes in the same step that snapshots the pending set | No |
| Matches how the docs describe it | "in `on_initialize`" as the rule, with the exact window in the reference | Exactly |

**Recommendation:** A, because "before the commit" is exactly the property parent D8 needs (the list
is complete when the instance is running), and it needs no hook-tracking flag. The commit snapshots
the pending declarations and pending values and closes the window synchronously, with no await between
the two, before it calls `submit()` (D10). After that, `add_*` raises, and a `set()` goes through the
normal write path, queued behind the commit on the single writer. The error is
`IntegrationDeclarationClosedError` (a `HassetteError`), naming the key, the platform and the rule. A
reloaded instance is a new object, so its window reopens.
**Pick B instead if** you want the docs' "in `on_initialize`" to be literally what's enforced.
**Reversibility:** easy (B is a narrowing of A).
**Ratified:** Chose keeping the declaration window open from instance creation until the running-time commit snapshots the pending set and closes the window in one synchronous step before `submit()`, with any later `add_*` raising `IntegrationDeclarationClosedError` and any later `set()` queued behind the commit, over enforcing only while the `on_initialize` hook runs, to tie the rule to the one state parent D8 needs, accepting that `before_`/`after_initialize` and in-init tasks may also declare.

### D8: Does this issue ship UI?

**Situation:** the issue's acceptance criteria say docs and UI ship with the code, per the repo's
design-completeness rule. The breakdown puts the monitoring UI in #4219, with the web API listing that
first makes the data servable. Nothing in this issue reaches the web API.

**Deciding factor:** UI ships in the issue whose API change makes the data visible.

**Recommendation:** no new UI here. Under D1-A each declaration's listener already shows in the
existing listeners view with its invocations. The declared-entity view lands with #4219, and the PR
body says so against the acceptance criterion.
**Pick a UI here instead if** you want the declarations visible before #4219, and accept pulling part
of #4219's listing into this issue.
**Reversibility:** easy.
**Ratified:** Chose shipping no new UI in this issue (handlers already show in the listeners view, and the declared-entity view lands with #4219's listing), over pulling part of #4219 forward, to ship UI with the API change that makes the data servable, accepting that the PR body records the acceptance criterion as met by #4219.

### D9: Where does the docs page go?

**Situation:** the parent requires a docs page with the `on_initialize`-only admonition, the
lookup-failure warning, the snap-back note (reworded for D11: HA shows the old state until the handler
calls `set()`, so call it first), the entity_id note, when to use code-created
helpers instead, and the hass-hassette requirement. App pages live in `docs/pages/core-concepts/apps/`
(`index.md`, `lifecycle.md`, `configuration.md`, `task-bucket.md`). hass-hassette setup lives on
`docs/pages/getting-started/home-assistant-integration.md`.

**Deciding factor:** found by an author who wants a button for an app.

**Recommendation:** a new page `docs/pages/core-concepts/apps/integration-entities.md`, linked from the
apps index, the HA integration page and `docs/pages/core-concepts/api/managing-helpers.md` (for the
code-created-helpers comparison), plus a harness section in `docs/pages/testing/harness.md`.
**Pick a section on the HA integration page if** you see it as part of the integration rather than of
writing apps.
**Reversibility:** easy.
**Ratified:** Chose a new page `docs/pages/core-concepts/apps/integration-entities.md`, cross-linked from the apps index, the HA integration page and the managing-helpers page, plus a harness section, over a section on the HA integration page, so authors find it while writing apps, accepting one more page in the apps section.

### D10: Who moves the in-memory copy after a database write, and what does an interrupted write leave?

**Situation:** the core service keeps two committed copies: the database rows, and memory (declarations,
entity state, revision). `DatabaseService.submit()` runs a started write to completion even when its
caller is cancelled or times out, and drops the result (`src/hassette/core/database_write_queue.py`,
`run_write_queue_worker` and `submit`). So a write has three outcomes: raised, committed and seen,
committed and unseen. Three paths make memory and the DB disagree: the running-time commit inside the startup
timeout (a `FAILED` instance would hold its new set, against parent D9); a `restart`-mode handler
cancelled mid-`set()` (the DB holds a value memory and HA never saw); and two concurrent `set()`
calls whose callers publish in the opposite order to their commits. A failed commit's effect on
pending values needs a rule too.

**Deciding factor:** settle the write/memory relationship once, so every edge falls out of one rule.

| | A: The write coroutine owns the publish; commit outside the timeout | B: Callers publish after `submit()`; patch each edge (re-read on cancel, a lock, an ordering rule) |
|---|---|---|
| Memory lags a committed write | Never: the same coroutine commits and publishes | Until a re-read, which can itself be cancelled |
| Publish order vs commit order | Same: the single writer's queue order | Needs a lock held across DB waits |
| Failed-init promise (parent D9) | Kept | Broken unless the re-read also rolls back |
| New mechanism | None | Re-read path and a lock |
| Prior art | Spec 132 D1.3 (the projector's baseline advances inside the write job, after commit); Kubernetes controllers | — |

**Recommendation:** A:
1. Every write (the running-time commit and each `set()`) runs as one coroutine
   on the DB writer that commits, then updates memory, then bumps the revision. Queue order is
   publish order.
2. The running-time commit runs after `inst.initialize()` returns, outside the startup-timeout block,
   bounded by `submit()`'s own timeout (which applies only until the write starts) and shielded from outer cancellation, so its outcome is always
   known. A failed commit takes the failed-init path.
3. A failed commit or failed init discards the instance's pending declarations and pending `set()`
   values; memory keeps the last committed set. During init, a handle reads its latest pending
   `set()` value if it has one, else its restored committed value, else (an entity not yet committed)
   a switch's `initial` or a sensor's `unknown`.
4. A `set()` whose caller is cancelled after its write started takes effect: a started write can't be
   withdrawn. One not yet started is withdrawn and changes nothing.
5. Around the commit: the instance's admission check (`admits_init`) runs again immediately before the
   snapshot, with no await between them, and an instance flagged or stopping there gets no commit. A
   stop that lands while the shielded commit is in flight keeps the committed set: init succeeded, so
   the list is complete (parent D9). Once started, the commit is awaited to completion like any started
   write, so a wedged database write holds the instance in `STARTING`; a caller-side timeout would
   bring back the committed-and-unseen outcome this decision removes.
6. `set()` updates a committed row and never creates one. A `set()` whose row doesn't exist (queued
   behind a commit that then failed) raises and leaves memory unchanged.
**Pick B instead if** memory is a plain cache with the DB authoritative and you want only the gaps written down.
**Reversibility:** easy (internal).
**Ratified:** Chose the write coroutine committing then updating memory then bumping the revision on the single writer, with the running-time commit moved outside the startup timeout and shielded, pending values discarded on a failed commit or init, and a cancelled caller's already-started `set()` taking effect, over callers publishing after `submit()` with per-edge patches, so memory never lags or reorders a committed write and a failed init never holds a new set, accepting that a `set()` write already started when its run is cancelled takes effect and that a wedged commit holds its instance in `STARTING`; a stop during an in-flight commit keeps the committed set, and `set()` never creates a row. Matches spec 132 D1.3; once spec 132 lands, #4219's listing reads these rows from the DB, and memory serves only handles and the per-boot revision.

### D11: Who changes a switch's state after a toggle? (supersedes parent D7)

**Situation:** parent D7 has the framework set the commanded value when the handler returns without
error, unless the handler called `set()` during that run, to spare every handler one line. "During that
run" needs a per-invocation identity: a flag on the handle is wrong under `parallel` and `restart`
(run A's `set()` would skip run B's auto-set), so it takes a contextvar cell per run, created by a
signature-preserving wrapper around each handler, reaching sync handlers and spawned tasks. Losing it overwrites the
value a handler chose, on the documented way to refuse a toggle. The same auto-set appears in parent
D6 ("the framework's post-handler write logs an error instead") and in the parent's Breakdown item 2
("the framework setting a switch's state after its handler succeeds"); this decision supersedes those
too.

**Deciding factor:** switch state changes only when something says so, with the least machinery.

| | A: The handler sets the state itself; the framework never auto-sets | B: Keep auto-set, tracking runs with a contextvar cell |
|---|---|---|
| Handler boilerplate | One `await self.<switch>.set(on)` per switch handler | None |
| Run tracking, wrapper | None; the handler registers as a plain listener | Contextvar cell, wrapper, tests across modes and sync handlers |
| Forgotten `set()` | The switch shows its old state again at the integration's next refresh; seen on first use | n/a |
| Rules to document | "State changes when you call `set()`" | Parent D7's set-then-raise, cancel and `parallel` rules |
| Peers | NetDaemon (app sets state), ESPHome (`write_state`) | None carry an auto-set |

**Recommendation:** A, because the only argument for auto-set was one line per handler, against a
wrapper, a per-run identity and a page of edge-case rules. The docs page shows `set()` as the handler's
first line, which is also the immediate-feedback advice parent D7's re-challenge asked for.
**Pick B instead if** the line per handler matters more than the tracking machinery.
**Reversibility:** easy (auto-set can be added later as an opt-in).
**Ratified:** Chose handlers setting switch state themselves with no framework auto-set over keeping parent D7's auto-set with per-run contextvar tracking, to match NetDaemon and ESPHome and drop the wrapper and run identity, accepting one `set()` line per switch handler and a switch that returns to its old state in HA when an author forgets it.

### D12: What happens to a restored value that no longer fits a changed declaration?

**Situation:** a kept `(key, platform)` row keeps its state across restarts (D4), and `set()` checks
value types (D5) only when called. If an app changes a sensor's device class, unit or `options` between
runs (numeric to enum, an option removed), the restored value is exposed on the handle and published to
HA although `set()` would now reject it. HA rejects such a value from a sensor entity and logs it. A
switch's restored value is always a bool, so only sensors are affected; a switch's `initial` is
written only when its row is first inserted (Summary, Persistence).

**Deciding factor:** a handle never holds a value its own declaration would reject.

| | A: At the commit, a restored value that fails the new declaration's check becomes `NULL` (`unknown`), with a WARNING | B: Keep it until the app's next `set()` |
|---|---|---|
| Handle and HA see an invalid value | No | Until the next `set()`; HA logs a rejection |
| Code | The D5 check run over kept rows inside the commit | None |
| Data lost | A value that no longer means anything under the new declaration | None |
| Peers | HA `RestoreSensor` restores unparseable stored data as `None` (unknown) (`tests/components/sensor/test_init.py`, `test_restore_sensor_restore_state`); HA's MQTT sensor sets an invalid date or timestamp to unknown with a WARNING (`components/mqtt/sensor.py`, `_update_state`) | HA's MQTT sensor ignores an invalid enum option and keeps the previous value, with a WARNING (same function); there it is a live message, not a restore |

**Recommendation:** A, because the D5 check already exists and running it inside the commit keeps the
"declaration and state agree" invariant at the one place they meet, so HA never receives a value it
would reject.
**Pick B instead if** you'd rather add nothing and let the app's next `set()` correct it.
**Reversibility:** easy.
**Ratified:** Chose resetting a restored sensor value that fails the new declaration's D5 check to `NULL` (`unknown`) inside the running-time commit, with a WARNING, over keeping it until the app's next `set()`, so a handle and HA never hold a value the declaration rejects, as HA's `RestoreSensor` does with unparseable restored data, accepting the loss of a value that no longer fits.

### D13: What does `set()` do with attributes, and does an unchanged `set()` write?

**Situation:** attributes persist with the value (parent D6), and the handle API is
`set(value, attributes=...)` (parent D12). Unstated: whether `set(5)` with no `attributes` keeps or
clears the previous attributes, and whether a `set()` that changes nothing commits and bumps the
revision. hassette's own `Api.set_state` merges attributes client-side on purpose, because HA's state
write replaces them (`src/hassette/api/entity_data.py`, `_set_state`).

**Deciding factor:** predictable state with no merge rules, and no needless writes from apps that
re-publish on a timer.

| | A: `set()` replaces value and attributes together; an identical `set()` is a no-op | B: Merge attributes (a separate way to clear them); every `set()` writes |
|---|---|---|
| `set(5)` after `set(4, attributes={"x": 1})` | Attributes become empty | `x` kept |
| Mirrors HA | Yes: an HA state write replaces attributes | No |
| Merge and clear rules to document | None | Merge semantics plus a clear API |
| Timer-driven re-publish of the same value | No write, no revision bump | A write and a revision bump every tick |
| Peers | HA `async_set` replaces attributes; MQTT `json_attributes_topic` replaces them per message | AppDaemon's `set_state` merges unless `replace=True` |

**Recommendation:** A, because it is what an HA state write does, needs no merge rules, and keeps a
sensor re-published every minute from writing to the DB every minute. "Identical" is decided inside
the write coroutine against the committed state (D10), so a `set()` queued behind others compares with
what actually committed; during init, a `set()` simply replaces the pending value.
**Pick B instead if** apps set attributes once and update the value often.
**Reversibility:** easy now.
**Ratified:** Chose `set()` replacing value and attributes together, with a `set()` identical to the current state a no-op (no write, no revision bump), over merging attributes with every `set()` writing, to match an HA state write and avoid timer-driven write churn, accepting that callers repeat attributes they want kept. This differs from `Api.set_state`, which merges on purpose; whether that should change is a separate question outside this issue.

## Assumed

Carried from the parent ledger (`design/specs/155-hacs-app-entities/design.md`), still holding against
current code:

- `self.integration` is the attribute; handle types don't reuse `*Entity` names. Parent D2.
- Revision: a per-boot identifier generated at each start plus a hassette-wide counter starting at zero
  each boot, bumped on every entity state change and on each declaration commit, in memory only. This
  issue owns and bumps them; #4219 and #4220 serve them. Parent D3. (The DB session id isn't usable as
  the boot identifier: it restarts at 1 when the database is recreated, which D3 rules out.)
- Switch and sensor state persisted by hassette, exposed on the handle at startup; a never-set sensor
  is `unknown`; a write is committed before the value is published; a failed `set()` leaves memory
  unchanged and raises; attributes are
  persisted with the value. Parent D6.
- Declarations only in init, with a specific error otherwise. Parent D8 (window detail is D7 here).
- Declarations collected in memory during init replace the persisted set in one transaction when the
  instance reaches `running`; `set()` during init is held and written in that commit. Parent D9.
- No hass-hassette installation check; docs state the requirement. Parent D10.
- Entity keys follow the `instance_name` rule (lowercase letters, digits, `_`), validated at
  declaration, unique per instance. Parent D11.
- Imperative awaited `add_*` returning handles; `set()` enforces the sensor type; a new switch starts
  off unless an initial value is passed; `add_*` takes the bus's execution-mode option, default
  `single`; values are JSON scalars or `null`; attributes JSON-serializable; optional suggested entity
  id. Parent D12.
- At startup, delete persisted rows for instances absent from the loaded config: no config entry for
  the `app_key`, or `instance_name` not among its configured instances. Disabled, `--app`-filtered and
  non-autostart apps are not absent. Parent D13.
- Integration entities rather than code-created helpers or MQTT. Parent D14.

Facts about the code:

- `DatabaseService.submit()` awaits a serialized write and raises the write's exception or
  `TimeoutError`. Evidence: `src/hassette/core/database_write_queue.py` (`submit`); listener and job
  registration use it (`src/hassette/core/command_executor.py`).
- `initialize_instance` runs `inst.initialize()` under the startup timeout, sends a failed init through
  `shutdown_instance`, and writes `RUNNING` afterwards. Evidence:
  `src/hassette/core/app_lifecycle_instances.py`.
- `ListenerMissReason` already has `busy` and `queue_full`, which are the drops `single` and `queued`
  modes produce. Evidence: `wire/src/hassette_wire/literals.py`.
- `classify_sensor_shape` and `DEVICE_CLASS` exist and track HA core. Evidence:
  `src/hassette/models/states/sensor_shapes.py`, `src/hassette/const/sensor.py`.
- The test harness runs no `DatabaseService`. Evidence: no reference to it under `src/hassette/testing/`.
- The latest migration is `026.sql`. Evidence: `src/hassette/migrations_sql/`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- `IntegrationService` is a `Resource`, not a `Service`: it has no serve loop, like `AppBootstrapCoordinator` and `SessionManager`.
- Keys are unique per instance across all three platforms (parent D11), which keeps listener names `integration.<platform>.<key>` unambiguous.
- A failed running-time commit runs the app's own shutdown hooks: `on_initialize` finished, so its cleanup applies, unlike a failed init.
- The admission re-check before the commit records its outcome the way `admits_init` already does (failed "stopped before init", or refused).
- Handle ownership is one rule (ship-time challenge): the service records which `Integration` committed each instance, and that `Integration` releases it when it shuts down. A `set()` whose owner doesn't hold the set raises `IntegrationHandleClosedError` inside its write job, which covers D10.6 (a `set()` queued behind a commit that failed) even when the previous run's row still exists, and a task leaked past a reload. `Integration` tracks its own phase (declaring, committing, committed, closed); a closed one's reads raise too. This replaces the Summary's "checked against that resource's lifecycle status": shutdown releases ownership, so the effect is the same.
- An instance that declares nothing and has nothing committed skips the commit: no write, revision bump or log line (ship-time challenge). An instance that had a set and now declares none still commits, so its rows go.
- Attributes are stored as a JSON round-trip copy, and a handle hands out copies, so mutating either side can't change committed state without a write (ship-time challenge). The identical-`set()` check stays Python `==`, as Home Assistant's own state machine does.
- D12's precedence (pending, else restored if it fits, else default) lives in one `resolve_state` in `declarations.py`, used by the handle's read during init and by the commit.
- A D12 reset sets the default state (a sensor's unknown, a switch's `initial`) and clears the attributes, which described the dropped value.
- During init a handle applies the D12 check to its restored value too, so it never reads a value its own declaration rejects.
- A stored value that doesn't parse loads as the default state with a WARNING.
- The table keeps a switch's `initial` in its own column, per D4's "typed columns for every field". It is read back only when a stored value doesn't parse: such a switch restores to its previously declared `initial`, which the next commit keeps.
- The harness press/toggle helpers live on a new `IntegrationSimulationMixin`: `_simulation.py` is already past the file-size limit.
- The two errors live in `hassette.integration.errors` (exported from `hassette`), since `exceptions.py` is at the 800-line limit.
- A sensor with no numeric, enum, timestamp or date shape accepts only `str` (D5's "else string"); a numeric sensor rejects non-finite numbers, which a JSON scalar can't carry.
- `IntegrationSyncFacade` is hand-written, not generated like `BusSyncFacade`: it mirrors three methods, and its `set()` takes a handle, a shape the codegen doesn't produce. A signature-parity test (`tests/unit/integration/test_sync_facade_parity.py`) keeps the `add_*` mirrors in step.
- `default_entity_id` is checked with HA's own `valid_entity_id`, which within D6's character set also rejects an object id starting or ending with `_`, ids HA itself would refuse.
- A stored row whose declaration doesn't parse (corrupt `options`) is skipped at load with a WARNING, rather than failing startup; the instance's next commit rewrites it as a new entity. A row whose value or attributes don't parse loads as the default state.

## Addendum

- 2026-11-19 (PR review): Two admission rules changed after D10 and D13 were built.
  - **Writes around the commit.** `Integration` holds its in-flight commit task. A `set()` during `COMMITTING` waits for that task, then writes (committed) or raises (closed), so ordering no longer depends on writer-queue order. The pending values stay readable until the commit settles. `_declare_with_handler` registers the listener before recording the declaration, reserving the key meanwhile. `IntegrationService.is_owner` stays the authority for writes already queued across a restart.
  - **Command admission.** `IntegrationService.admit_command` is the single check for `dispatch_command` and the harness simulation: `not_running` when the instance has no live owner (committed and not released; a commit landing after shutdown never takes ownership), `not_declared` when the key isn't committed. It replaces the app registry status read, which a late RUNNING write at process exit could satisfy.
  - **Release on every stop.** Every stop closes the instance's Integration (`Integration._close`, called from the `finally` of `AppLifecycleService.shutdown_instance`, which covers walk-aways), and closing releases ownership. This corrects the build note that the Integration releases ownership "when it shuts down".
  - **Log identity.** `LogIdentityFilter` keeps an explicit `extra=` app_key/instance_name pair on ownerless loggers, so the service's per-instance warnings carry their subject.

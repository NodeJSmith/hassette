# Design: UI-Editable App Config Overrides

**Date:** 2026-08-11
**Updated:** 2026-08-13 — rebased onto #1605 (`AppRegistry` instance unification), which satisfied this design's hard prerequisite and changed the app-key locking it depends on. See Architecture (Locking) and Dependencies and Assumptions.
**Status:** draft
**Scope-mode:** hold
**Research:** `design/research/2026-08-11-ui-config-overrides/` — `config-precedence-prior-art.md` (where comparable systems store UI-set config and how they resolve conflicts), `form-library-prior-art.md` (JSON Schema form libraries, benchmarked against React 19), `cli-config-set-prior-art.md` (CLI write-command ergonomics)

## Problem

App configuration lives only in `hassette.toml`. Changing a single tuning parameter — the class times an OrangeTheory booking app uses, a threshold, an offset — means opening a file on the host, editing TOML, and getting the app to reload. For a value a user adjusts regularly, that is disproportionate friction, and it is friction that has survived two prior attempts to remove it.

Issues #489 (runtime config changes via API) and #490 (persist changes to `hassette.toml`) were both closed in May 2026 citing `design/research/2026-05-02-frontend-exposure-interactivity/research.md`. The closing comments state a stricter position than that research took: line 187 of the research explicitly endorses *"Edit config for operational parameters (schedules, thresholds, enable/disable): **Yes, persisted**"*, ruling out only structural config (which entities a handler watches, handler logic). Tuning parameters are the endorsed case, not the excluded one.

What actually blocked the work was a design question that looked unresolvable: if the UI can change config, where does the value live, which source wins, and how does a user know? Writing back to `hassette.toml` runs into a read-only config mount, destroys comments and formatting, and — as Zigbee2MQTT demonstrates — silently reverts env-controlled fields while writing the reverted value to disk in the same save that was meant to store the edit.

That constraint turns out to be false in hassette's case. `data_dir` (default `/data`) is already separate from `config_dir`, already created and writable, and already holds the telemetry database and an atomically-written credential sidecar. Nothing needs to write to the user's config file.

## Goals

- A user changes an app config value from the web UI, the change takes effect without further action, and it survives a hassette restart.
- The same operation is available from the CLI with equivalent capability, not a reduced subset.
- At any point, a user can see where a config value came from — schema default, `hassette.toml`, a higher-precedence source, or a UI/CLI override — and revert an override to the file value.
- A value set through the UI can never silently outrank a source that documented precedence says should beat it.
- A bad value cannot break an app silently. A value that fails validation never reaches disk; one that fails only at runtime leaves the app visibly `FAILED` and one action from reverted, the same way a bad `hassette.toml` edit does today.

## Non-Goals

- **Editing global `HassetteConfig`.** Same machinery would apply, but the blast radius differs — changing `data_dir` or Home Assistant connection settings mid-run is not a per-app reload. Deferred to its own decision; #539 tracks exposing that surface read-only.
- **Home Assistant helper-entity-backed config fields.** A genuinely separate feature: declaring a config field as backed by an `input_number`/`input_datetime` so Home Assistant's own UI tunes it. Cheaper and gives true read-on-next-use with no restart, but it answers a different question and only covers helper-shaped types.
- **Override history or an audit trail.** Only current state is stored.
- **Editing `SecretStr` fields at all**, including write-only. Secrets stay in `hassette.toml`, `.env`, or the environment.
- **Multi-user attribution.** The web API authenticates with a single shared token, so provenance can record *that* a value was set via API but never *who* set it.

## User Scenarios

### App operator: runs hassette for their own home

- **Goal:** change a tuning parameter on a running app without editing files
- **Context:** at a laptop or phone, hassette already running, app already working

#### Change a value from the web UI

1. **Open the app's Config tab**
   - Sees: every config field with its current effective value and a provenance marker (default / file / override / shadowed)
   - Then: the read-only view renders immediately; the editable form loads in behind it
2. **Edit one or more fields**
   - Sees: edited fields marked dirty; a change count; fields that cannot be edited are disabled with the reason stated on the field itself
   - Decides: which values to change; whether to discard
   - Then: a save control appears, labeled with its consequence — saving restarts the app
3. **Save**
   - Sees: in-progress state, then one of three outcomes — confirmation that the app reloaded, a validation error mapped to the offending field with nothing saved, or a notice that the change was saved but the app did not come back up, with a revert affordance
   - Then: validation failure persists nothing and the form stays dirty; both other outcomes persist the override and refetch the config view — including the runtime failure, where the value is saved and the app is left `FAILED` until reverted
4. **Revert a field later**
   - Sees: a revert affordance on any overridden field
   - Then: the override is removed, the field returns to its file value, the app reloads

#### Change a value from the CLI

1. **Inspect** — `hassette app config <key>` shows values annotated with provenance, per instance for a multi-instance app
2. **Set** — `hassette app config set <key> field=value other=value` writes both in one operation and one restart; `--instance` names the target when the app has more than one
3. **Revert** — `hassette app config unset <key> field`

### App author: writes apps others run

- **Goal:** control nothing extra; existing apps become tunable with no code change
- **Context:** writing a normal `AppConfig` subclass

#### Ship a tunable app without opting in

1. **Define a normal `AppConfig` subclass**
   - Then: every non-excluded field is editable through UI and CLI automatically; no annotation, no registration, no new base class

## Functional Requirements

- **FR#1** A persisted override store holds per-app, per-instance field overrides in a JSON sidecar under `data_dir`, separate from `config_dir`.
- **FR#2** Overrides are layered over the per-instance config dict immediately before `AppConfig` validation, so an app receives a single validated config object and cannot tell an override from a file value.
- **FR#3** An override records the effective pre-override value it was written against, whether that field was present at all, and the field's base generation at the time of writing.
- **FR#4** On the app-creation path, an override whose recorded base generation is behind the field's current base generation is suppressed — not applied, and not deleted.
- **FR#5** An override for a field that is no longer present in the app's config schema is dropped and not applied.
- **FR#6** An override for a field sourced from a higher-precedence source (environment variable or `.env` file) is not applied, and is reported as shadowed rather than silently ignored.
- **FR#7** A single server-side predicate determines whether a given field is editable, returning a machine-readable reason when it is not.
- **FR#8** The config read response carries, per field, the effective value, its source, whether it is editable, the reason it is not, and its schema default.
- **FR#9** The same predicate gates the write path — a write to an uneditable field is rejected regardless of what any client displayed.
- **FR#10** A write accepts multiple field changes and removals in one request and produces exactly one app reload.
- **FR#11** A write is validated against the full merged config model, not against the patch in isolation, so cross-field validators run.
- **FR#12** A write is rejected if it names a field absent from the app's config schema, despite `AppConfig` permitting extra keys.
- **FR#13** A write is rejected if it names a `SecretStr` field.
- **FR#14** A write persists the override once the merged model validates, then attempts the reload. An override that fails validation never reaches disk.
- **FR#15** If the app does not come back up, the override remains persisted, the app is left in its `FAILED` state visible through the existing status surface, and the write response reports that outcome rather than claiming success.
- **FR#16** A write against a stale view of the config is rejected rather than overwriting a concurrent change.
- **FR#17** Saving config for a stopped app persists the override without starting the app and without triggering a reload.
- **FR#18** The web UI renders an editable form generated from the app's config schema, with uneditable fields disabled and their reason displayed on the field.
- **FR#19** The web UI accumulates edits and submits them as one save, with a discard action and a per-field revert on overridden fields.
- **FR#20** After a successful write, the client refreshes the config view rather than waiting for a pushed event.
- **FR#21** The CLI sets one or more fields in one invocation, coercing values using the schema the server already returns.
- **FR#22** The CLI removes one or more overrides, and can combine removals with sets in a single operation.
- **FR#23** The CLI accepts a whole override document for bulk or scripted use.
- **FR#24** A CLI coercion failure names the field, the expected schema type, the received value, and the correct syntax.
- **FR#25** The CLI config read annotates each field with its provenance.
- **FR#26** A failure to persist the override store surfaces as an error, never as a silent no-op.
- **FR#27** A write targets exactly one app instance. When an app has more than one instance, the target must be named explicitly; a write that does not name one is rejected rather than defaulting to the first.
- **FR#28** The config read surfaces per-instance values for a multi-instance app, so a caller can tell which instance an override belongs to.
- **FR#29** A field's base generation advances whenever a reconcile observes its effective pre-override value differ from the last observed value, in either direction. A value that changes away and later changes back advances the generation twice and never restores a suppressed override. (Extends FR#4.)
- **FR#30** A record is removed from the store only by an explicit user unset or by orphan pruning. Reconciliation never deletes. (Extends FR#4.)
- **FR#31** A suppressed override is a distinct provenance state, reported as such rather than being indistinguishable from a field that was never overridden. (Extends FR#4.)

## Edge Cases

- **Reload restarts every instance of an app key.** `stop_app` unregisters all instances, so editing one instance of a multi-instance app restarts all of them. Not worth reworking the lifecycle for; stated in UI copy and docs. Note this is a distinct concern from *targeting*: a write changes exactly one instance's overrides (FR#27) even though the resulting reload restarts all of them.
- **Instance selector omitted on a multi-instance app.** Rejected with the available instances listed, never defaulted to index 0. A write that silently edits the wrong instance is worse than one that fails.
- **Env var added after an override exists.** FR#6 stops it applying, but the override still sits in the store. Reported as shadowed on the field, not silently dropped — dropping it would lose the user's value if the env var is later removed.
- **Field removed from the app's model.** `AppConfig` sets `extra="allow"` (`app/app_config.py:20`), so a stale override would otherwise survive as an unvalidated extra key. FR#5 drops it.
- **`instance_name` renamed in `hassette.toml`, or the app removed.** Overrides orphan. Orphans are pruned when encountered rather than accumulating.
- **Two clients writing at once.** The existing per-app-key lock serializes the writes but does not prevent last-writer-wins across two stale reads. FR#16 covers it.
- **Reload fails after applying an override.** The merged model validated — this is not a validation failure — but the app did not come back up with it. FR#15: the override stays persisted, the app is left `FAILED`, and the response reports the app's resulting status. The user reverts the field to recover. This is deliberately the same outcome a bad `hassette.toml` edit produces today, rather than a stronger guarantee that exists only for override writes. It does mean a runtime-bad override survives a restart until reverted — accepted, and recorded in Dependencies and Assumptions.
- **Override store unwritable** (read-only `data_dir`, disk full). FR#26 — a silent degrade would show file values while the user believes they saved.
- **Editing a failed app.** Unlike a stopped app, saving a *failed* app does attempt a restart — fixing config is how a user recovers a failed app.
- **`.env` file provenance.** `.env` values never reach `os.environ` (see Architecture), so a naive environment check misclassifies them as file-sourced.
- **Crash between persisting and reloading.** The override is durable but not yet live. On the next start it applies through the normal merge point, so the outcome converges on what the user asked for. The client never sees a false success, because the route awaits the full sequence before responding. Named rather than left implicit; this is the safe failure direction and needs no further handling. (Under the earlier persist-after-confirm draft this window ran the other way — live but not durable — which is why it is worth stating explicitly that the ordering changed.)
- **Corrupt override file.** Treated as empty, logged at ERROR. Startup must never fail because this file is malformed; degrading to file config is behavior users already understand.

## Acceptance Criteria

- **AC#1** Unit tests cover the override store: load, atomic save, corrupt-file degradation, stale-base drop, orphan prune. (FR#1, FR#3, FR#4, FR#26)
- **AC#2** A unit test proves an override is applied to the config an app receives, and a second proves an override whose recorded base has changed is not applied. (FR#2, FR#4)
- **AC#3** A unit test proves a field set via a `.env` file is reported as shadowed and its override is not applied, with `os.environ` empty of that key during the test. (FR#6)
- **AC#4** A unit test proves an override for a field absent from the schema is dropped, and an integration test proves a write naming such a field is rejected. (FR#5, FR#12)
- **AC#5** Unit tests cover the editability predicate across every reason it can return, including the boundary that `instance_name` and `app_key` are `RESERVED` while `log_level` and the other base `AppConfig` fields are editable. An integration test proves the write path rejects each uneditable case independently of the read response. (FR#7, FR#9, FR#13)
- **AC#6** An integration test proves a multi-field write produces exactly one reload. (FR#10)
- **AC#7** An integration test proves a write violating a cross-field model validator is rejected with a 422 naming the fields. (FR#11)
- **AC#8** An integration test proves a stale-version write is rejected without changing stored state. (FR#16)
- **AC#9** An integration test proves saving config for a stopped app persists without starting it. (FR#17)
- **AC#10** A system test proves an override that fails validation is never written to disk, and a second proves a config that validates but fails at runtime is persisted, leaves the app `FAILED`, and is recoverable by reverting the field. (FR#14, FR#15)
- **AC#11** Frontend tests prove the editable form disables uneditable fields and renders their reason, accumulates edits into one save, and refetches after success. (FR#18, FR#19, FR#20)
- **AC#12** A characterization test for the existing read-only renderer passes unchanged before and after the read/edit split.
- **AC#13** CLI tests at both layers — cyclopts dispatch and direct call — cover set, unset, combined set-and-unset, and bulk document input. (FR#21, FR#22, FR#23)
- **AC#14** A CLI test asserts a coercion failure message contains the field name, the expected type, and the received value. (FR#24)
- **AC#15** A CLI test proves the config read output carries provenance annotations. (FR#25)
- **AC#16** An e2e test performs the full round trip: edit a value in the browser, observe it take effect, restart hassette, observe it persist.
- **AC#17** `prek -a` and `prek pyright -a --stage pre-push` pass.
- **AC#18** `npm run size` passes — the entry chunk stays within its 240 kB gzip budget with the form library present.
- **AC#19** An integration test asserts the config read response carries, for each field, all five descriptor attributes — effective value, source, editable flag, reason when not editable, and schema default — including a field of each source kind (default, file, override, shadowed). (FR#8)
- **AC#20** An integration test proves a write to a multi-instance app without an instance selector is rejected, and a write naming one instance leaves the other instance's overrides untouched. A CLI test covers the same via `--instance`. (FR#27)
- **AC#21** An integration test proves the config read for a multi-instance app returns values per instance. (FR#28)
- **AC#22** An integration test proves a config that passes model validation but leaves the app not running returns a success response reporting `failed` status — not a 422 — with the override persisted. A second proves the partial case: a multi-instance app where one instance fails reports the per-instance statuses rather than blanket success. (FR#15)
- **AC#23** An integration test proves a write to a *failed* app attempts a reload, distinct from the stopped-app path which does not reload. Both persist. (FR#14, FR#17)
- **AC#24** An integration test proves a write naming an instance that does not exist returns 404, distinct from the missing-selector 409 in AC#20. (FR#27)
- **AC#25** An integration test proves that when the override store cannot be written, the response is a 500 and the failure is not silently swallowed. (FR#26)
- **AC#26** A unit test walks the A→B→A round trip: an override is written while the file reads A, suppressed when the file changes to B, and **remains suppressed** when the file returns to A. (FR#4, FR#29)
- **AC#27** A unit test proves reconciliation never deletes a record — a suppressed override is still present in the store afterward and is restored by neither the file changing again nor a reload, only by an explicit unset. (FR#30)
- **AC#28** An integration test proves a suppressed override is reported as its own provenance state, distinguishable from a field that was never overridden. (FR#31)
- **AC#29** An integration test proves the write-generation token rejects a stale write with 409, and that a write to one app does not invalidate an outstanding token for a different app. (FR#16)
- **AC#30** An integration test proves a config write against a running app completes rather than deadlocking on the app-key lock, asserted under `asyncio.wait_for` so a regression surfaces as a timeout instead of a hung suite. (FR#15)
- **AC#31** The existing `reload_app` unit tests pass unchanged after the `_reload_app_unlocked` extraction, pinning it as pure code motion.
- **AC#32** A CLI test proves `set` renders a `failed` write result with the app status and the revert command, and a `degraded` result naming which instances came up — not a bare success line. (FR#15)

## Key Constraints

- **Never write to `hassette.toml` or anything under `config_dir`.** The whole design exists to avoid it. Comment destruction, read-only mounts, and the env-revert data-loss bug all follow from that one move.
- **The UI must never be the only thing enforcing editability.** Grafana's read-only guard was UI-only and users bypassed it with raw API calls, which destroyed trust in the feature. Read descriptor and write rejection come from one function.
- **Do not derive field provenance by reading `os.environ`.** `.env` values never appear there during config construction. See Architecture.
- **Do not rely on `Hassette.startup_tasks()`'s `load_dotenv()` side effect.** It does populate `os.environ` before apps are built, which makes an `os.environ`-only predicate appear to work under `hassette run` — but it is gated on `import_dot_env_files`, a user-settable field, and does not apply on any path that builds config without going through `Hassette.start()`.
- **Do not hot-swap `app_config` on a running instance.** Apps read config in `on_initialize` and turn it into scheduled jobs and listeners; swapping the object afterward would report new values while continuing to fire on the old ones.
- **Do not determine reload success by counting survivors.** Read each instance's status directly from `AppRegistry.get_instances()`, which returns every tracked slot carrying a `status`. Do not reconstruct the picture by diffing running instances against the manifest's configured instance count.
- **Do not call `AppLifecycleService.reload_app()` while holding the app-key lock.** `_get_app_key_lock` returns a non-reentrant `asyncio.Lock` with no timeout, and `reload_app` acquires it itself — a handler that holds it and then calls `reload_app` hangs permanently. Use the unlocked body instead. See Architecture (Locking).
- **Do not build a transactional apply/rollback into `AppFactory.create_instances`.** It is on every app-creation path in the framework, so a trial-apply mode there risks all app startup, not just override writes. Validation before persistence is the safety property that matters; runtime failure is handled by the existing `FAILED` status surface, not by an automatic revert.
- **`--json` is already a global output flag.** It cannot be repurposed as a CLI input mode.

## Dependencies and Assumptions

Accepted costs, each traceable to a decision made during discovery:

- **Two sources of truth.** `hassette.toml` no longer fully describes what is running. Mitigated by provenance display on every field in both UI and CLI, and by the stale-base rule that drops an override when the file changes underneath it. Accepted when the direction was chosen.
- **Every save restarts the app.** In-flight work is cancelled, in-memory state is lost, and jobs are dropped and recreated. Mitigated by form-level save (one restart regardless of how many fields change) and by naming the consequence on the save control. Accepted when the save UX was chosen over per-field inline save.
- **A new frontend dependency and a lazily-loaded chunk.** Mitigated by the size budget applying to the entry chunk only, so the library never enters the measured path. Accepted when the form library was chosen over hand-rolling.
- **Framework-grade scope, not one-app-grade — and this is what the design's size buys.** The motivating case is one field on one app. Nearly all of the requirement count instead serves a broader goal stated in User Scenarios: any `AppConfig` subclass becomes tunable with no code change from its author. That goal is what pulls in the schema normalizer, the form library, three of the editability predicate's reasons, multi-instance targeting, and CLI parity. It is the right default for a framework whose users write their own apps — requiring an annotation to get tunability would mean nothing existing is tunable, which is why per-field opt-in was rejected — but it is a deliberate choice with a real cost, not a free consequence of the feature. Recorded here because every other major scope choice in this design got that treatment and this one had been assumed. Accepted during adversarial review.
- **A third artifact users must back up.** `data_dir` now carries real configuration alongside `hassette.toml` and the apps directory, and downgrading strands the file on disk. Mitigated in documentation. Accepted when reversibility was assessed.
- **A runtime-bad override survives restarts until reverted.** An override that validates but breaks the app at runtime stays persisted; the app stays `FAILED` across restarts until the user reverts the field. Mitigated by the write response reporting the failure immediately, the app being visibly `FAILED` rather than silently wrong, and FR#19's per-field revert. Accepted deliberately during adversarial review, in exchange for keeping transactional apply/rollback out of `AppFactory.create_instances` — see Alternatives Considered. This is the same outcome the framework already produces for a bad `hassette.toml` edit.

**Prerequisite — the `AppRegistry` instance-state refactor — has landed.** This design's status reporting requires `AppRegistry` to expose a single per-instance state map in which every instance is present carrying a status, rather than the two parallel dicts where `record_failure` moved an instance out of `_apps` into `_failed_apps`. That was tracked as **#1597** and shipped in **#1605** (`14f8c4b5`). What this design now builds against:

- `AppRegistry._instances: dict[str, dict[int, InstanceEntry]]` — one entry per instance slot, always present. `InstanceEntry` is a frozen dataclass carrying `app`, `status`, and the error payload when failed.
- `get_instances(app_key) -> dict[int, InstanceEntry]` — every tracked instance, running and failed, each with its status. This is the read the status report uses.
- `get_running_apps(app_key)` — the renamed `get_apps_by_key`, running instances only.
- `ManifestStatus.DEGRADED` — a manifest whose instances are a mix of running and failed, with existing frontend treatment (warning tone, filter option, stop/reload enabled).
- `clear_failures()` and `iter_all_instances()` are gone; stale failed indices are pruned by `prune_stale_failed_indices(app_key, valid_index_count)`.

Assumptions:

- The web API's single shared token is sufficient authorization for config writes. `auth_enabled` defaults to `True` and `auth_enabled=False` is refused on a non-loopback host (`config/models.py:360-370`), so a fresh install is protected without configuration.
- Real-world `AppConfig` subclasses rarely declare `Any`-typed or permissively-unioned fields, so schema-driven CLI coercion resolves nearly every value. Measured by `grep -rn "class .*(AppConfig)" --include='*.py' examples/ tests/ src/`, which finds 46 subclasses: exactly one field contains `Any`, and it is `handler_calls: list[Any]` in a test harness. Note the methodology excludes `docs/**/snippets`, where a broader grep finds more matches; documentation examples were deliberately left out as illustrative rather than real. This is weak evidence about user apps regardless, since they do not live in this repo. Mitigated by the fact that a per-pair JSON escape (`field:=<json>`) can be added later without breaking existing `field=value` calls.

## Architecture

### Where overrides live

A JSON sidecar at `<data_dir>/app_config_overrides.json`, structured as `{app_key: {instance_name: {field: record}}}`. Each record holds the override value, the effective pre-override value it was written against, whether that field was present at all, and a timestamp.

**Staleness is a generation fence, not a value comparison.** Each field carries a base generation: a counter the store advances whenever a reconcile observes the field's effective pre-override value differ from the value last observed. An override records the generation current when it was written, and is applied only while that generation is still current.

The distinction matters because value equality answers "does my recorded before-state still describe the file?" — which is not the same question as "am I still the most recent expression of user intent for this field?" Only the second is safe across an unbounded timeline. Under value equality, a field that goes A → B → A restores the original comparison and silently reactivates an override the user may have set months earlier and watched get suppressed in between. Under a generation fence, the same round trip advances the counter twice and the override stays suppressed, because the fence records *that* the file moved, not *where it moved to*.

Suppression is not deletion. A record is removed only by an explicit unset or by orphan pruning; reconciliation only ever declines to apply. This keeps a suppressed override recoverable and is what makes the Migration section's reactivation-on-reinstall language coherent. It also means suppression needs to be visible: a suppressed override is its own provenance state, never rendered as "this field was never overridden."

`base_value` and `base_present` are retained for display — showing the user what the file said when they set the override — but are not the staleness test. `base_present` exists because JSON cannot distinguish "the file said `null`" from "the file did not mention this field". Keying by `instance_name` rather than index is deliberate: `manifest.app_config` is a positional list, so reordering a multi-instance `[[hassette.apps.<key>.config]]` array would silently rebind every override. `instance_name` is guaranteed present — `AppManifest.validate_app_config` (`config/classes.py:178-194`) injects `{class_name}.{idx}` when unset, before `AppFactory` ever reads it.

Writes are atomic: temp file in the destination directory, then `Path.replace()`. This generalizes the pattern already used for `<data_dir>/.web_api_token` (`web/auth/tokens.py:121-141`) into a shared utility rather than copying it.

A JSON sidecar rather than a telemetry-DB table because "delete the file to get back to pure file state" is a valuable recovery property, and because the telemetry DB is a derived store — `app_manifests` is a one-way snapshot cache, not a system of record.

### Where overrides are applied

`AppFactory.create_instances` (`core/app_factory.py:53-77`) normalizes `manifest.app_config` to a list of dicts and calls `app_class.app_config_cls.model_validate(config)`. The override merge, the stale-base reconciliation, and the schema-key filter all happen between those two steps.

This point was verified rather than assumed: with `HASSETTE__APPS__PRESENCE__CONFIG__MOTION_SENSOR` set, `manifest.app_config` carries the environment value merged with the remaining TOML keys. The dict at the merge point is the fully source-merged one, so precedence can be reasoned about locally. It exists only after `set_validated_app_manifests()` has run, which is guaranteed on every path that reaches `create_instances` — `Hassette.startup_tasks()` at startup (`core/core.py:164`), `HassetteConfig.reload()` on a config reload (`config/config.py:341-350`).

Because this one function serves both startup and reload, reconciliation needs no separate scheduling and no file-watcher hook — which matters, since the watcher is gated on `dev_mode or allow_reload_in_prod` (`core/app_handler.py:79`) and is off in a default production deployment. A `hassette.toml` edit in production is observed the next time the app is created, which is exactly when it matters.

For a multi-instance app, `reconcile()` resolves an override's file config by scanning `manifest.app_config` for the entry whose `instance_name` matches, not by indexing positionally.

### Determining provenance and editability

One function answers "where did this field's value come from, and may it be changed", returning either editable or a structured reason: `SHADOWED`, `SECRET`, `NOT_IN_SCHEMA`, or `RESERVED`.

There is deliberately one `SHADOWED` reason rather than separate env and dotenv variants. The reason enum's only job is explaining *why* a field cannot be edited; *where* the winning value came from is already carried by the per-field `source` (FR#8), which the UI and CLI read anyway. Splitting the distinction across both vocabularies would duplicate it across the three consumers that have to stay in sync — the read descriptor, the write rejection, and the CLI presenter — which is precisely what the single-predicate rule exists to prevent. The env-vs-dotenv difference is still worth surfacing, because ".env file" and "environment variable" are different fixes; it is surfaced once, from `source`.

`RESERVED` covers exactly two fields — `instance_name` and `app_key` — and the reason is mechanical, not stylistic: `instance_name` is the override store's own key, so overriding it would orphan every override for that instance the moment it took effect, and `app_key` is the app's identity. Both are declared on the base `AppConfig` (`app/app_config.py:27,33`), and `app_key` already carries a validator rejecting framework-reserved values.

`RESERVED` is deliberately **narrower** than the existing `_FRAMEWORK_FIELDS` list (`web/routes/apps.py:52`, surfaced as `AppConfigResponse.framework_fields` and already used by the config tab to group a "Hassette Settings" section). That list is `set(AppConfig.model_fields) | set(_MANIFEST_FIELD_SCHEMAS)`, and it serves display grouping, not editability. Three groups have to be told apart:

- **Base `AppConfig` fields other than the two reserved ones** — `log_level`, `forgotten_await_behavior`, `blocking_io_behavior` — are ordinary per-instance settings and **are** editable. Turning down an app's log level from the UI is a legitimate use of this feature, not an escape from it.
- **`enabled` and `autostart`** are the entire contents of `_MANIFEST_FIELD_SCHEMAS` (`web/routes/apps.py:39-48`). They are injected into the config *view* for display but are manifest properties, not `AppConfig` fields, so they never reach the dict `AppFactory` validates. A write naming one is `NOT_IN_SCHEMA`.
- **`filename` and `class_name`** are neither. They are top-level attributes on `AppManifest` and on `AppConfigResponse` (`config/classes.py:122,125`; `web/models.py:503-504`) and appear in no schema at all — not `config_schema`, not `_FRAMEWORK_FIELDS`. A write naming one is `NOT_IN_SCHEMA` for the same reason any unknown key is.

The practical consequence: `_FRAMEWORK_FIELDS` cannot be used to derive the uneditable set. It omits `filename`/`class_name` and includes editable fields like `log_level`. Editability comes from the predicate, which decides per field; `_FRAMEWORK_FIELDS` is reused only for the frontend's existing "Hassette Settings" grouping. Changing which file an app loads from remains a structural change that belongs in `hassette.toml`.

Do not reuse `_FRAMEWORK_FIELDS` as the reserved set; reuse it for display grouping only. It feeds three consumers — the read response's per-field descriptor, the write path's rejection, and the CLI presenter — so a client cannot display one rule while the server enforces another.

**Provenance cannot be derived from `os.environ`.** A `.env` file is parsed into a local mapping and never mutates the process environment. Verified by experiment on pydantic-settings 2.11.0: a `.env`-set field beat the TOML value inside `apps.apps` while its key never appeared in `os.environ`, before or after config construction. (The experiment inspected `DotEnvSettingsSource._read_env_files()` to confirm the mechanism — that citation is evidence for *this document*, not a dependency surface. See below.)

**Implement against the public callable protocol, not a private method.** The predicate calls the source objects — `EnvSettingsSource` and `DotEnvSettingsSource` — through their standard `__call__()`, the same opaque contract `settings_customise_sources` already relies on (`config/config.py:65-81`). Do not reach for `_read_env_files()` or any other underscore-prefixed method: a leading underscore carries no compatibility promise, and a rename in a patch release would surface as an `AttributeError` deep inside a per-app config read at runtime rather than as a review-time failure. That matters more here than in most projects, since hassette's audience includes other people's apps.

Pin the dependency with a test: instantiate `EnvSettingsSource`/`DotEnvSettingsSource` directly against a `HassetteConfig`-shaped model and assert the returned mapping's shape for a nested-delimiter field, so a pydantic-settings bump that changes the callable's return shape fails loudly in CI instead of silently producing wrong provenance. A predicate reading only `os.environ` would classify that field as TOML-sourced — the lowest-precedence source — and let an override defeat it. Provenance is resolved by consulting pydantic-settings' own `env_settings` and `dotenv_settings` sources for the field's nested path.

The search space is smaller than the full precedence chain suggests. `secrets_dir` is never configured, so `file_secret_settings` contributes nothing. `hassette run` builds init kwargs for only five top-level fields (`cli/commands/run.py:23-65`), so `init_settings` can never source a per-app config field. Only env and dotenv need checking. Within env, only the `__` delimiter form resolves an arbitrary nested path — `HASSETTE_APPS_APPS_...` does not — but matching is case-insensitive, since `case_sensitive` defaults to `False`.

The editability check runs at merge time, not only at write time. An environment variable added after an override was stored must win, which it cannot do if the check happens only when the override is written.

### Applying a change

The sequence is linear, with no transactional apply and no automatic revert:

1. **Validate** the merged whole model. A failure here returns 422 and nothing is written — this is the safety property that actually matters, because it catches every override that could not possibly work.
2. **Persist** the override atomically.
3. **Reload**, unless the app is stopped.
4. **Report** the app's resulting status in the response.

Only the reload step varies by app state:

- **Running** — reload.
- **Stopped** — do not reload. Starting an app the user deliberately stopped would be a surprising side effect of editing a value; the override applies the next time it starts, through the same merge point.
- **Failed** — reload. Fixing config is how a user recovers a failed app, so this path must be able to start it.

**Why there is no rollback.** An earlier draft applied the override transiently, reloaded, confirmed, and only then persisted — restoring the previous config if the app did not come back. That was rejected during challenge for two reasons. It required a trial-apply mode inside `AppFactory.create_instances`, which is on every app-creation path in the framework, so a defect there would break all app startup rather than just override writes. And it duplicated recovery the framework already provides: a config that breaks an app produces `ResourceStatus.FAILED` on the instance (surfacing as `ManifestStatus.FAILED` or `DEGRADED` on the manifest), surfaced through the same status and health views as any other broken app, which is exactly what a bad `hassette.toml` edit does today.

The cost is real and accepted: an override that validates but fails at runtime stays persisted and the app stays `FAILED` across restarts until the user reverts the field. The write response says so immediately, the app is visibly broken rather than silently wrong, and FR#19's per-field revert is one action. Building a stronger guarantee for override writes than the framework gives file edits would be inconsistent scope, not extra safety.

**Reporting the resulting status.** After the reload, the response reports each targeted instance's status by reading it from `AppRegistry`. This is a status report, not a gate — nothing is rolled back on a mismatch. It exists so the response and the UI tell the truth about what happened, including the partial case where some instances of a multi-instance app came up and others did not.

The read is `AppRegistry.get_instances(app_key)` — every tracked slot, each carrying its status. No counting, no manifest cross-reference, no consultation of a separate failure log. The partial case is directly expressible because a failed instance stays in the map at `FAILED` rather than being moved out of it.

This was not expressible before **#1605** landed, which is why that refactor was sequenced ahead of this work. The interim workaround — counting survivors against `len(manifest.app_config)` — was considered and rejected then, and is now moot.

The check is meaningful because `initialize_instances` awaits `inst.initialize()` in a plain loop (`core/app_lifecycle_service.py:163-225`) with no `TaskBucket.spawn`, and records each outcome to the registry inline, so by the time the reload's await returns, every instance's status is already recorded — determinate, not racing.

`reload_app` keeps its public signature and its exception-swallowing behavior. The success signal is derived from registry state by the caller, which keeps the change off the shared lifecycle path used by the file watcher and the existing HTTP routes.

**Locking.** The write handler holds the per-app-key lock (`_get_app_key_lock`) across its entire sequence — version check, merge, persist, reload, and status report — rather than taking it only for the reload.

Two writers must not interleave here. Without the widened hold, both could pass their version check, both reload, and each run its status report outside the lock — writer A observing writer B's freshly-`RUNNING` instances and reporting success for a config that is no longer the one running. Holding the lock across the whole handler closes that window for this feature's own path.

**The handler must not call `reload_app()` while holding the lock.** Since **#1605**, `reload_app` acquires `_get_app_key_lock` itself (`core/app_lifecycle_service.py:629`), as do `start_app` (`:480`) and `stop_app` (`:572`). `_get_app_key_lock` returns a plain non-reentrant `asyncio.Lock` with no timeout, so a handler holding it and then awaiting `reload_app` deadlocks permanently — not a slow path, a hung request. #1605 hit the same edge internally and solved it by extracting `_stop_app_unlocked` / `_start_app_unlocked` and having `reload_app` acquire the lock once and call those bodies directly.

This design follows that established pattern rather than working around it: **extract `_reload_app_unlocked(app_key, force_reload)`** carrying exactly the code *inside* `reload_app`'s `async with self._get_app_key_lock(app_key)` block — the `_stop_app_unlocked` call, the manifest lookup and its early return, and the `_start_app_unlocked` call. Nothing else moves. `_admit_start` and the surrounding `try`/`except` stay in the public `reload_app`, which becomes admission check → `try` → lock acquisition → one call to `_reload_app_unlocked`. This is the same split `start_app` already uses (`core/app_lifecycle_service.py:460-491`), where pre-lock work stays in the wrapper because `_admit_start` can block indefinitely before the lock is ever reached.

The config-write path is a method on `AppLifecycleService`, so it reaches admission the same way `reload_app` does rather than needing a private method from outside the class. Its sequence is:

1. `await self._admit_start(app_key=app_key, admission_mode=AppAdmissionMode.REJECT_IF_UNRELEASED)` — **before** acquiring the lock, matching `reload_app`'s ordering. In `REJECT_IF_UNRELEASED` mode this raises `AppBootstrapNotReleasedError` rather than waiting, which is the behavior the `409` needs; `WAIT_FOR_RELEASE` would block a user's request indefinitely and is never used here.
2. Acquire `_get_app_key_lock(app_key)` and hold it for the rest: version check, merge, persist, reload via `_reload_app_unlocked`, status report.

The route in `web/routes/apps.py` stays thin and maps `AppBootstrapNotReleasedError` through the existing `_raise_bootstrap_not_released` helper (`web/routes/apps.py:68-70`), the same path `start_app` and `reload_app` already use. That is where the `409` in the status-mapping table comes from — the write handler does not reimplement the check.

Rejected alternative: having the handler inline `_stop_app_unlocked` + `_start_app_unlocked` itself. It needs no new lifecycle method, but the handler would then carry a second copy of `reload_app`'s body — including the "manifest missing, skip" branch — which drifts the moment either copy changes. Also rejected: narrowing the lock so it is not held across the reload, which sidesteps the deadlock by giving up the interleaving guarantee the widened hold exists to provide.

The broader gap — that a lifecycle operation for one app key is unserialized against *other* entry points that do not take this lock at all (bootstrap, reconciliation paths) — is pre-existing and tracked as **#1227**. This design does not depend on that fix; it takes the lock itself.

Concurrency: two clients reading the same state and both writing would otherwise last-writer-wins. The config read response carries a version token, and a write carrying a stale one is rejected with 409.

The token is a **write generation counter stored per `(app_key, instance_name)`** as a sibling field inside that instance's node in the existing JSON structure, incremented on every write or prune that touches that node. It rides the atomic write already committed to, so it needs no separate persistence or recovery story.

Rejected alternative: a hash of the effective config plus the override file's mtime. Three defects, any one disqualifying. The store is a single shared file, so a write or an orphan-prune for *any* app bumps the one mtime and invalidates every other app's outstanding token — spurious 409s for edits unrelated to what changed. Plain `st_mtime` is coarse enough that two writes in quick succession (a combined set-and-unset, or `--from-json`) can land in the same tick; this repo already hit exactly that and `utils/source_capture.py:38-42` uses `st_mtime_ns` to avoid it. And "hash of the effective config" has no canonical serialization, so semantically identical configs could hash differently between reads. A per-instance counter is immune to all three because it is scoped to the entity being edited and derives from nothing outside the record.

Also rejected: dropping optimistic concurrency entirely and relying on the per-app-key lock plus the field-scoped request body. Defensible for a single-operator tool — a lost update would cost one field, recoverable by re-saving — but the counter achieves the same leanness without giving up the guarantee, so there is little to buy by removing it.

Note the two counters in this design are different mechanisms answering different questions, and must not be merged: the **base generation** (per field) tracks whether the underlying file value has moved, and the **write generation** (per instance) tracks whether another client has written since this client read.

### HTTP surface

A mutating route on the existing apps router, following the established shape (`web/routes/apps.py:151-168`): shared `_validate_app_key` / `_require_known_app` guards, `response_model` set, domain exceptions mapped to status codes, peer address logged.

It departs from that shape in one respect. Existing mutating routes return `202 Accepted` and let the resulting state arrive over the WebSocket. This route awaits the reload and returns the resulting app status, because the user needs to know in the same interaction whether the value they just saved actually started the app — a `202` would report only that the write was accepted, which is never in doubt once validation passes.

**There is exactly one mutating route, not a write route and a delete route.** FR#10 requires sets and removals to travel in one request and produce one reload, so the request body carries both:

```
{ "version": "<token>", "set": { "<field>": <value>, ... }, "unset": ["<field>", ...] }
```

The CLI's standalone `unset` and the UI's per-field revert both submit this same shape with an empty `set`. Clearing every override for an instance is an `unset` naming each overridden field. A second DELETE endpoint would need its own reload and status semantics — a duplicate of everything below, for no capability the one route lacks.

The route targets one instance. An app with a single instance may omit the selector; an app with more than one must supply it, and a write without one is rejected rather than defaulting to index 0 — silently editing the wrong instance is worse than an error.

Status mapping:

| Status | Case |
|---|---|
| `404` | Unknown app key, or a named instance that does not exist |
| `403` | A named field is not editable (secret, shadowed, not in schema, reserved) |
| `409` | Stale version token, app bootstrap not released, or a multi-instance app with no instance named |
| `422` | The merged model failed validation. Carries per-field errors; nothing was persisted |
| `500` | The override could not be persisted |

There is no body-level discriminator on `422`. It has exactly one meaning — schema validation failed — because a runtime startup failure is no longer an error response at all: the write succeeded, the override is persisted, and the app's resulting state is reported in the success body.

The response carries the post-reload status as a `ManifestStatus`, reusing the framework's existing vocabulary rather than inventing a parallel one. The partial case is `ManifestStatus.DEGRADED`, which **#1605** introduced for exactly this situation — a manifest whose instances are a mix of running and failed — so the response needs no expected-versus-actual instance counts and the UI needs no new status to render. Per-instance detail comes from `get_instances()` and is included alongside it, so a user editing one instance of a multi-instance app can see which slot failed.

A client renders a `422` as field-level errors, a `failed` status as a "saved, but the app didn't start" notice with a revert affordance, and `degraded` through the warning-tone treatment already wired into the apps view.

### Frontend

`ConfigSchemaView` (`components/shared/config-schema-view.tsx`) is documented as a read-only renderer and every leaf renders a span. Rather than threading an `editable`/`onChange` flag through `SecretValue`, `BoolValue`, `ListValue`, `ExpandableValue`, and the path/duration/enum branches, it splits:

- **Read renderer** — the existing component, eagerly loaded, unchanged in behavior. Its current tests become the characterization pin for the split.
- **Edit renderer** — `@rjsf/shadcn`, `React.lazy`-loaded, rendered behind the read view so the page paints immediately and the form swaps in when its chunk arrives.

The size budget applies to the entry chunk only (`frontend/.size-limit.json` — `index-*.js`, 240 kB gzip), so a lazily-loaded form library never enters the measured path. This is what makes the library affordable: measured marginal cost is +108.6 kB gzip against roughly 8 kB of headroom, which would be disqualifying in the entry chunk and is unremarkable in a route chunk. #1477 (entry-chunk code-splitting) is therefore not a prerequisite.

Provenance renders through stock rjsf: a `uiSchema` built at runtime from the server's per-field descriptors, with `ui:disabled` from `editable` and `ui:help` from `disabled_reason`. Verified by rendering it — the emitted markup carries both the `disabled` attribute and the reason text, and `ui:help` renders unconditionally rather than being suppressed when disabled. No theme fork, no custom widget per type, no custom `FieldTemplate`.

**A schema normalizer is required regardless of library.** Pydantic emits `anyOf: [X, null]` for `X | None`, which rjsf renders as a spurious type selector labeled "…option 1 / …option 2" with the null branch preselected — the base `AppConfig` has two such fields, so every user app inherits it. Fixed tuples emit `prefixItems`, which renders no controls at all, silently. Collapsing `anyOf:[X,null]` to `X` and `prefixItems` to `items` fixes both; upstream issues rjsf-team/react-jsonschema-form#4843 and #4380.

Writes use the existing `apiPost`/`apiPut` helpers and the `useAsyncAction` + `sonner` error handling from `ActionButtons`, but deliberately diverge on refresh: on success the client invalidates the config query rather than waiting for a WebSocket push. This establishes `invalidateQueries` as the write convention — `@tanstack/react-query` is already a dependency but has no non-test invalidation call today. A user-initiated write needs a confirmed post-state, not an eventually-arriving event.

A CLI-initiated write does not push an invalidation to open browsers. Rejected alternative: extending the WebSocket protocol to carry config-change events — disproportionate for a single-user tool where the page refetches on focus.

### CLI surface

```
hassette app config set <key> field=value other=value
hassette app config set <key> studios='["1234","5678"]'
hassette app config set <key> mode=heat --unset lead_days
hassette app config set <key> --instance office field=value
hassette app config unset <key> field other
hassette app config set <key> --from-json -
```

Instance targeting reuses the CLI's established convention rather than inventing one: `InstanceArg` plus `client.resolve_instance(key, instance)`, as already used by `app health` and `app activity` (`cli/commands/app.py:60,71,83,94`). It accepts an integer index or an instance name. Omitting it is valid only for a single-instance app; for a multi-instance app the command errors and lists the available instances rather than defaulting.

Note that `cmd_app_config` does not take `--instance` today — the read command is app-key-only and returns whatever the response carries. FR#28 extends the read to surface per-instance values, so both halves of the CLI can address the same unit.

Variadic positional `FIELD=VALUE`. Values are coerced using `config_schema`, which `AppConfigResponse` (`web/models.py:490-501`) already returns and the CLI currently discards — so a list-typed field accepts a JSON literal without a separate flag.

Rejected alternative: helm's `--set` / `--set-json` / `--set-string` family. Those flags accreted over years precisely because helm has no schema and must guess types; hassette has the schema on the wire. Also rejected: positional `key value` — no surveyed tool that supports batched writes uses it, and batching matters here because each write costs a restart.

`--unset` on `set` exists so a revert and a set share one restart, which a separate subcommand cannot express. The standalone `unset` subcommand covers the common case.

Terraform uses this same schema-driven model and it is the right one, but shipped with diagnostics opaque enough that users fail repeatedly (hashicorp/terraform#17032). Coercion errors here name the field, the expected schema type, the received value, and the correct syntax.

**The CLI reports the post-write status too.** The write route returns a `ManifestStatus` plus per-instance detail regardless of which surface called it, so `set`/`unset` must render that rather than printing a bare success. A `running` result is an ordinary success line; `failed` prints the app's status and the revert command for the fields just written, so the recovery action is on screen at the moment it is needed rather than requiring a separate `app health` call; `degraded` names which instances came up and which did not, using the per-instance detail. A `stopped` result states that the override was saved and applies on next start, so a user who deliberately stopped the app is not told it failed.

A per-pair JSON escape (`field:=<json>`) is deliberately not in v1. Adding it later does not break existing `field=value` calls — a value containing `:=` after the first `=` parses unambiguously — so the option stays open at no cost.

## Implementation Preferences

- **`@rjsf/shadcn`** for the editable form, `React.lazy`-loaded. Not hand-rolled: array add/remove/reorder, `additionalProperties` editing, and dirty/error plumbing are exactly the parts that are easy to underestimate and get subtly wrong.
- **cyclopts** for CLI commands, matching the existing `app.meta.default` launcher and `CLIContextParam` threading. Note that cyclopts 4.15.0 cannot accept JSON into a `dict[...]` parameter in any tested configuration, which is why the CLI shape uses variadic positionals rather than a `--values` mapping.
- **pydantic** models for the override store's on-disk shape, giving JSON round-tripping and validation without hand-written parsing.
- **`whenever`** for the override timestamp — `Instant.now().format_iso()` on whenever 0.10.
- Follow `web/CLAUDE.md` for route conventions, including `response_model=` on every decorator.

## Replacement Targets

- **`frontend/src/components/shared/config-schema-view.tsx`** — split, not deleted. The read-only rendering path survives as the eager renderer; the assumption that it is the *only* renderer is what goes away. Its existing tests are pinned first and must pass unchanged after the split. Do not add an `editable` mode flag to it.
- **`src/hassette/cli/commands/app.py:118-119`** — currently discards `config_schema` from the CLI response as "a large machine-oriented blob". The write path needs it for coercion, so it is retained internally and excluded only from rendered output.

## Migration

No schema migration and no change to how existing config loads. The override file does not exist until the first override is written, and its absence is indistinguishable from today's behavior.

Reverting the code strands `<data_dir>/app_config_overrides.json`. Apps fall back to file values, which is correct, but silently. If the feature is later reinstalled, stored overrides reactivate — the stale-base rule catches those whose file value changed in the interim, but not those whose file value is unchanged. Documented rather than coded against.

## Convention Examples

### Mutating web route

**Source:** `src/hassette/web/routes/apps.py:151-168`

```python
@router.post(
    "/apps/{app_key}/start",
    status_code=202,
    response_model=ActionResponse,
    responses={409: {"description": "App bootstrap prerequisites are not ready yet; retry later"}},
)
async def start_app(app_key: str, hassette: HassetteDep, request: Request) -> ActionResponse:
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette)
    try:
        await hassette.app_handler.start_app(app_key)
    except AppBootstrapNotReleasedError as exc:
        _raise_bootstrap_not_released(exc)
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to start app %s", app_key, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start app") from exc
    LOGGER.info("Started app %s (source=%s)", app_key, peer_address_or_unknown(request))
    return ActionResponse(status="accepted", app_key=app_key, action="start")
```

### Atomic sidecar write under `data_dir`

**Source:** `src/hassette/web/auth/tokens.py:121-141`

```python
def _write_token_atomic(token_path: Path, token: str) -> None:
    tmp_path = token_path.with_name(f"{token_path.name}.tmp-{os.getpid()}")
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        tmp_path.replace(token_path)
    except OSError as exc:
        with suppress(OSError):
            tmp_path.unlink()
        raise AuthTokenWriteError(token_path, exc) from exc
```

### CLI command structure

**Source:** `src/hassette/cli/commands/app.py:105-122`

```python
def cmd_app_config(
    key: str,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show app configuration (GET /api/apps/{key}/config).

    Renders the app's metadata and masked config values. The fully-inlined
    ``config_schema`` is part of the response but is intentionally not shown — it is a
    large machine-oriented blob, not something a CLI reader needs.
    """
    client = make_client(ctx)
    result = client.get(f"/api/apps/{key}/config", AppConfigResponse)
    # Render every field except config_schema, the large machine-oriented blob. Dumping the
    # model (rather than naming fields) keeps new AppConfigResponse fields visible automatically.
    detail = {field: value for field, value in result.model_dump(mode="json").items() if field != "config_schema"}
    render_detail_dict(detail, "App Config", json_mode=ctx.json_mode)
```

Note the comment on the dict comprehension: dumping the model rather than naming fields means new `AppConfigResponse` fields appear in CLI output automatically. Adding per-field provenance to the response therefore surfaces in the CLI without touching this function — but as an opaque nested dict until `output.py` learns to annotate it.

### Web route test

**Source:** `tests/integration/web_api/test_endpoints.py:147-166`

```python
async def test_start_app(self, client: "AsyncClient") -> None:
    response = await client.post(APP_START_PATH)
    assert response.status_code == 202
    data = response.json()
    assert data["action"] == "start"

async def test_start_app_returns_retryable_conflict_before_release(
    self, client: "AsyncClient", mock_hassette: MagicMock
) -> None:
    mock_hassette.app_handler.start_app = AsyncMock(side_effect=AppBootstrapNotReleasedError("not released"))
    response = await client.post(APP_START_PATH)
    assert response.status_code == 409
```

### Frontend component test

**Source:** `frontend/src/components/app-detail/config-tab.test.tsx:60-67`

```tsx
describe("ConfigTab", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/apps/:app_key/config", () => {
        return HttpResponse.json(defaultConfig);
      }),
    );
  });
```

### Frontend mutation — DO/DON'T

**Source:** `frontend/src/components/shared/action-buttons.tsx:53-67`

```tsx
// The request returns 202 — the toast confirms the action was accepted, the
// resulting status change arrives later over the WebSocket.
const exec = (name: ActionName) => {
  const { request, verb, outcome } = ACTIONS[name];
  return run(async () => {
    try {
      await request(appKey);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to ${verb} "${appKey}": ${message}`);
      throw err;
    }
    toast.success(`App "${appKey}" ${outcome}`);
  });
};
```

**DO** copy the `useAsyncAction` concurrency guard and the toast-on-both-paths error handling. **DON'T** copy the refresh strategy — the comment describes exactly what this feature must not do. Config writes await their outcome and invalidate the query; they do not return early and wait for a push.

## Alternatives Considered

- **Write back to `hassette.toml` (issue #490's approach).** Preserves a single source of truth and stays git-friendly. Rejected: `tomli-w` destroys comments and formatting on every save; it needs write access to `config_dir`; the file watcher would need self-write suppression; and env-shadowed fields reproduce Zigbee2MQTT's silent data loss, where a UI edit is reverted and the reverted value written to disk in the same save. The two systems that do this — Zigbee2MQTT and Frigate — are the two with the worst documented read-only-mount failures.
- **In-memory overrides only (issue #489's approach).** Simple, no persistence question. Rejected: fails the requirement that changes survive a restart.
- **Hot-swapping `app_config` with an `on_config_changed` hook.** Avoids the restart entirely. Rejected: apps turn config into scheduled jobs and listeners during `on_initialize`, so a swap would report the new value while continuing to fire on the old schedule — silently wrong for the motivating use case, unless every app author implements the hook.
- **Splitting persist from apply (Frigate's `Save` vs `Save & Restart`, HA add-ons' save-then-prompt-restart).** Rejected, though less emphatically than an earlier draft of this document claimed. Save and apply stay one action because a user editing a value wants it in effect, and a deferred-apply mode adds a second state ("saved but not live") the UI would have to represent. Note this design *does* persist before the app is proven — the earlier draft did not, and the argument that persisting first is unacceptable no longer applies; see "Why there is no rollback."
- **Transactional apply with automatic rollback** (apply the override transiently, reload, confirm, restore the previous config and persist nothing if the app does not come back). This was the original design and was rejected during adversarial review. It required a trial-apply mode inside `AppFactory.create_instances` — the single highest-blast-radius path in the framework, on every app-creation path — and it duplicated recovery the framework already provides through `ResourceStatus.FAILED`. Two defects were also found in the specified version: the transient in-memory state was never stated to be unwound before the restore attempt, and there was no defined outcome for the rollback restart itself failing (`App` extends `Resource`, not `Service`, so no `ServiceWatcher` supervision catches it). The cost of rejecting it is stated in "Why there is no rollback" and accepted in Dependencies and Assumptions.
- **Home Assistant helper entities as the tunable surface.** Near-zero framework work, no precedence problem at all, no restart, and the value becomes visible to HA automations and dashboards. Rejected as the answer to *this* problem because it is a different UI and only covers helper-shaped types — but it remains attractive as a separate feature.
- **Per-field opt-in (`json_schema_extra={"ui": {"tunable": True}}`).** Makes the editable surface a deliberate contract. Rejected: nothing is tunable until authors annotate, which fails the "existing apps just work" goal.
- **Hand-rolling the editable form.** No new dependency, fits the entry-chunk budget trivially. Rejected: the boring parts are where the bugs live, and the budget objection dissolves once the renderer is lazily loaded.
- **`@jsonforms/react` and `uniforms`.** Rejected on verification, not preference: `uniforms` fails installation against React 19 and has been idle since January; JSONForms rendered 6 of 13 fields from a real pydantic schema with no markup and no error for the rest.
- **Do nothing.** The status quo — edit `hassette.toml`, restart. Rejected: this is the friction being removed, and the two prior attempts to remove it were closed against a position stricter than the research they cited.

## Test Strategy

### Required Test Types

- **Unit** — the override store, the editability predicate, the schema normalizer, and the merge/reconcile logic are all single-module concerns.
- **Integration** — the HTTP routes and the `AppFactory` merge path cross module boundaries; `tests/integration/web_api/` with `create_hassette_stub()` is the established setup.
- **CLI, both layers** — `tests/unit/cli/CLAUDE.md` requires `test_parse_args.py` (cyclopts dispatch) in addition to `test_commands_*.py` (direct calls). A bug shipped once because only the direct-call layer existed and the converter was never exercised.
- **Frontend** — vitest + `@testing-library/react` + MSW, colocated.
- **System** — this touches `core/app_factory.py` and `core/app_lifecycle_service.py`, and the persist-then-reload path plus its per-instance status reporting are lifecycle-timing-sensitive, which is precisely where unit and integration mocks hide regressions.
- **E2E** — the round trip spans frontend and backend and is the stated success bar.

No gaps: every layer already has infrastructure. CI runs the system and e2e suites on every push, so neither needs to run locally during development.

### Existing Tests to Adapt

- `frontend/src/components/shared/config-schema-view.test.tsx` — pinned as the characterization test before the read/edit split, then must pass unchanged.
- `frontend/src/components/app-detail/config-tab.test.tsx` — the tab gains an editable path; existing read assertions must continue to hold.
- `tests/unit/test_app_factory.py` and `tests/integration/test_app_factory_lifecycle.py` — `AppFactory` gains a constructor dependency on the override store; both construct it directly and need updating.
- `src/hassette/test_utils/web_mocks.py` — `create_hassette_stub()`'s `app_action_mocks=True` pre-mocks start/stop/reload; the config-write path needs an analogous hook.
- `tests/unit/core/test_app_lifecycle_service_operations.py` — the existing `reload_app` coverage is the behavior pin for the `_reload_app_unlocked` extraction. It must pass unchanged afterward; the extraction is code motion, so any assertion that has to be edited to stay green is evidence the motion was not pure.

### New Test Coverage

Mapped to FRs in Acceptance Criteria above. The behaviors that most need coverage at the layer that can actually catch them: generation-fence suppression (including the A→B→A round trip) and dotenv shadowing at unit level, since both are pure logic with a subtle rule; per-instance status reporting after a partial reload failure at system level, since it depends on real lifecycle timing; the round trip at e2e.

One case needs a test that would not otherwise be written: **the write handler completes while holding the app-key lock.** A regression that reintroduces the `reload_app`-under-lock deadlock does not fail loudly — it hangs, and a suite without a timeout hangs with it. Cover it with an integration test that performs a config write against a running app wrapped in `asyncio.wait_for` with a short timeout, so the failure mode is a timeout error rather than a stalled run.

### Tests to Remove

No tests to remove. The read renderer's tests are retained as the split's characterization pin.

## Documentation Updates

- `docs/pages/core-concepts/apps/configuration.md` — a section on UI/CLI overrides: where they are stored, that they layer over the file, when they are dropped, and that a higher-precedence source still wins.
- `docs/pages/web-ui/inspect-config-code.md` — update for the editable path and the restart consequence. Note that line 27's existing claim — the tab "shows the raw TOML values, not the merged result" — becomes factually wrong once FR#8 ships effective-value descriptors, so it must be rewritten, not just appended to.
- CLI reference — `hassette app config set` / `unset`, including the coercion rules and the `--from-json` escape hatch.
- Backup guidance — `<data_dir>/app_config_overrides.json` now carries real configuration and must be backed up alongside `hassette.toml` and the apps directory. Note that removing the feature reverts apps to file values.
- Docstrings on the new public surfaces, per Google style.
- Per `.claude/rules/design-completeness.md`, the config tab is documented with a screenshot — regenerate the affected `docs/_static/web_ui_*.png` via `scripts/capture_screenshots.py --only <name>` after the UI lands.

## Impact

### Changed Files

Shared and cross-cutting first:

- `src/hassette/core/app_factory.py` — **modify**: accept the override store; merge, reconcile, and schema-filter before `model_validate`.
- `src/hassette/core/app_lifecycle_service.py` — **modify**: extract `_reload_app_unlocked` from `reload_app` (pure code motion, mirroring #1605's `_stop_app_unlocked` / `_start_app_unlocked`); construct the override store; add the config-write path (validate → persist → reload → report), holding the per-app-key lock across the whole sequence and calling `_reload_app_unlocked` rather than `reload_app`.
- `src/hassette/web/config_view.py` — **modify**: add per-field provenance descriptors alongside the existing masking.
- `src/hassette/web/models.py` — **modify**: per-field descriptors and a version token on the config response; a request model for writes.
- `src/hassette/core/config_overrides.py` — **create**: the override store and its on-disk models.
- `src/hassette/core/config_provenance.py` — **create**: the editability/provenance predicate.
- `src/hassette/utils/atomic_write.py` — **create**: shared atomic write, generalized from `web/auth/tokens.py`.
- `src/hassette/web/auth/tokens.py` — **modify**: use the shared atomic write.
- `src/hassette/web/routes/apps.py` — **modify**: one config write route accepting an instance selector and a combined set/unset body. No separate delete route.
- `src/hassette/cli/commands/app.py` — **modify**: `set`/`unset` commands with `InstanceArg`; per-instance, provenance-annotated read.
- `src/hassette/cli/__init__.py` — **modify**: register the new subcommands.
- `src/hassette/cli/output.py` — **modify**: provenance annotation in rendered read output; post-write status rendering for `running` / `failed` / `degraded` / `stopped`.
- `src/hassette/test_utils/web_mocks.py` — **modify**: stub hook for config writes.
- `frontend/src/components/shared/config-schema-view.tsx` — **modify**: split out the read path.
- `frontend/src/components/shared/config-edit-form.tsx` — **create**: the lazily-loaded rjsf renderer.
- `frontend/src/lib/schema-normalize.ts` — **create**: `anyOf`/`prefixItems` normalization.
- `frontend/src/components/app-detail/config-tab.tsx` — **modify**: compose read and edit renderers, save/discard/revert.
- `frontend/src/api/` — **modify**: config write client functions and query invalidation.
- `frontend/package.json` — **modify**: rjsf dependencies.
- `openapi.json`, `frontend/src/api/generated-types.ts` — **regenerate** via `scripts/export_schemas.py --types`.
- Tests and docs per the sections above.

### Behavioral Invariants

- An app with no overrides behaves exactly as today — same config, same startup, same reload.
- `hassette.toml` is never written to.
- Documented precedence holds: a value from a higher-precedence source is never defeated by an override.
- `reload_app`'s public signature, locking, and exception behavior are unchanged by the `_reload_app_unlocked` extraction; the file watcher and the existing start/stop/reload routes are unaffected.
- The read-only config view keeps working for apps whose class is not loaded, where no schema is available.
- Secrets are never returned unmasked and never accepted as input.
- The entry chunk stays within its size budget.

### Blast Radius

`AppFactory.create_instances` is on every app-creation path, so a defect there affects all app startup, not just apps with overrides — the highest-risk change in the feature. The `_reload_app_unlocked` extraction sits on the shared reload path used by the file watcher and the existing REST routes; it is pure code motion with no behavior change, but a mistake in it is not scoped to override writes. `web/config_view.py` is shared by the global config page and the per-app tab, so descriptor changes touch both. The shared atomic-write extraction touches auth token writing. Everything else is additive.

## Open Questions

None. Every item raised during discovery and the blind-spot pass was resolved, decided, or recorded above as an accepted risk in Dependencies and Assumptions.

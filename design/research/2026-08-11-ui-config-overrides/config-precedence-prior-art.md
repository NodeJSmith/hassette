# Prior Art: File Config + UI-Editable Runtime Parameters

Survey for the hassette "change an app parameter from the web UI, persist it, apply on next
execution, no file editing, no restart" problem. Focus: **precedence, provenance, persistence** —
not UI cosmetics.

Scope note: this is prior art only. No hassette code was modified.

---

## TL;DR — the five findings that matter

1. **Nearly every mature system refuses to write back to the user's config file.**
   systemd writes drop-ins to a *different directory*. HA writes `.storage/*.json`. Sentry and
   django-constance write DB rows. HA add-ons write `apps.json` + `/data/options.json`. The two
   systems that *do* rewrite the user's own YAML (Zigbee2MQTT, Frigate) are the two with the
   worst documented failure modes. This makes the read-only-mount problem mostly self-solving:
   if you never write the TOML, you never need it writable.

2. **Sentry's option registry is the closest complete design** — per-key declared policy flags,
   a provenance tag on every read (`"disk" | "store" | "default"`), a server-computed
   `can_update()` returning a structured reason, and one decision function feeding both a CLI and
   a REST surface. See §7.

3. **Provenance has two proven shapes**: `systemctl cat`'s per-line `# /path/to/file` comment
   (best *visual* model) and Sentry's `{value, disabled, disabledReason, isSet}` per-field API
   triple (best *API* model). Paperless's cheaper variant — no per-field badge, just a **Reset**
   button that appears only when an override exists — is the minimum viable version.

4. **The dominant complaint across every system is the same**: the lock is binary and coarse where
   users want graduated trust, and "the file wins on next reload" silently discards UI work with
   no diff shown at the moment of loss. Grafana re-litigated this twice (dashboards, then alerting)
   without generalizing the fix.

5. **Zigbee2MQTT is the cautionary tale to design against**: env vars unconditionally win over UI
   edits, *and* the reverted value is persisted to disk in the same write cycle that was meant to
   save the user's edit, with zero UI indication. Two individually reasonable features composing
   into silent data loss.

---

## 1. Home Assistant Core — `.storage` vs YAML

### (a) Where mutable values live
`<config>/.storage/*.json`, one file per key (`core.config_entries`, `input_number`, ...), written
through `homeassistant.helpers.storage.Store`. Envelope is
`{"version", "minor_version", "key", "data"}`. Saves are debounced via `async_delay_save()`
(helpers using `StorageCollection` set `SAVE_DELAY = 10`s). Optional `atomic_writes=True` uses
write-temp-then-rename. `_async_migrate_func()` is the per-key schema migration hook.
Source: [storage.py](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/storage.py),
[collection.py](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/collection.py)

### (b) Precedence
For device/service integrations there is no merge — ADR-0010 decided these are **UI-only**:
> "Integrations that communicate with devices and/or services are only configured via the UI."
> "Changes to existing YAML configuration for these same existing integrations, will no longer be accepted."

Leftover YAML re-triggers the import flow every boot, hits `_abort_if_unique_id_configured()`,
aborts `already_configured`, and becomes an inert trigger for a repair reminder. The config entry
drives behavior.
[ADR-0010](https://github.com/home-assistant/architecture/blob/master/adr/0010-integration-configuration.md)

For helpers/automations/scripts a deliberate **hybrid** exists: `YamlCollection` and
`StorageCollection` both feed the same `EntityComponent`, producing sibling entities that differ
only in an `editable` state attribute.

### (c) Provenance
`editable` is a public state attribute set at construction:
`from_storage()` → `editable = True`; `from_yaml()` → `editable = False`.
([input_number/__init__.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/input_number/__init__.py))

Frontend renders a greyed crossed-out pencil (`mdiPencilOff`) + tooltip. Actual strings, verbatim
from `frontend/src/translations/en.json`:

| Surface | String |
|---|---|
| Helpers list | "Unmanageable" |
| Automation editor | "This automation cannot be edited from the UI, because it is not stored in the automations.yaml file, or doesn't have an ID." |
| Script editor | "This script cannot be edited from the UI, because it is not stored in the 'scripts.yaml' file." |
| Person | "People configured via configuration.yaml cannot be edited via the UI." |
| Zone | "Zones configured via configuration.yaml cannot be edited via the UI." |
| Voice assistant | "Configured in YAML, not editable in UI" |
| Lovelace resources | "Your resources are in YAML mode, therefore you cannot manage them through the UI." |
| Settings → General | "Editor disabled because config stored in configuration.yaml." |

**Note the inconsistency** — no shared component or string; each panel wrote its own copy.

Important nuance: `editable: false` gates the helper's *definition* (name/min/max/step), **not its
current value**. A YAML-defined `input_number`'s value is still settable from the UI. This is
exactly the split hassette wants — the parameter is tunable, its declaration is not.
([community thread](https://community.home-assistant.io/t/make-input-uneditable-in-ui/272235))

### (d) Read-only config dir
Not directly addressed; `.storage` lives inside the config dir, so HA assumes it is writable.

### (e) How change takes effect
Helper *values* are entity state — read live on every template evaluation, no restart. Helper
*definitions* from YAML need `input_number.reload` or a restart.

Config entries: options flow writes `entry.options` (distinct from `entry.data`);
`async_update_entry()` diffs, persists, and fires `update_listeners` only if something changed.
`OptionsFlowWithReload` auto-reloads the integration. This is the canonical
"change a param → takes effect on next run, no full restart" mechanism.
([options flow docs](https://developers.home-assistant.io/docs/config_entries_options_flow_handler/))

### (f) Complaints
- YAML-created helpers showing as non-editable, with no in-UI path to convert. Maintainer response:
  "That's by design... it's unlikely the Core development team will change it now."
  ([thread](https://community.home-assistant.io/t/allow-editing-of-helpers-input-boolean-input-text-input-number-etc-in-both-gui-and-yaml/795138))
- `.storage` mixes config with runtime state, breaking git-tracked configs
  ([architecture#370](https://github.com/home-assistant/architecture/issues/370)).
- **One YAML key disables an entire settings surface**: a leftover `homeassistant:` block silently
  killed the whole Settings → General editor
  ([frontend#14628](https://github.com/home-assistant/frontend/issues/14628)).
- Writing UI config back into YAML was explicitly proposed and rejected:
  "Thanks for your interest in this topic but this is not something that we would consider right now."
  — @balloob, [architecture#400](https://github.com/home-assistant/architecture/issues/400#issuecomment-646733611)

**Epistemic flag:** the popular "they refused because YAML round-trip destroys comments" framing is
**not** directly quoted anywhere the agent could find. ADR-0010's stated reasoning is different —
discovery/OAuth config can't be expressed as static YAML at all, and `!secret` was already a
workaround signaling the format's limits. Treat comment-loss as plausible-but-unsourced.

---

## 2. HA Add-ons / Supervisor — the closest structural analogue

Immutable add-on definition + schema, mutable user options in a writable data dir. (Note: the
Supervisor repo renamed add-ons → "apps" on `main`; paths below reflect current source.)

### (a) Where mutable values live — **two stores, different authority**
- **`/data/apps.json`** (Supervisor's own store, was `addons.json`): `AppsData` holds
  `system[slug]` (a *snapshot* of the add-on's `config.yaml` defaults, captured at install/update)
  and `user[slug]` (persisted overrides). This is the live source of truth for user intent.
- **`/data/options.json`** (inside the add-on container): a point-in-time materialization the
  running process actually reads.

### (b) Precedence
```python
_OPTIONS_MERGER = Merger(type_strategies=[(dict, ["merge"])],
                         fallback_strategies=["override"],
                         type_conflict_strategies=["override"])
@property
def options(self): return _OPTIONS_MERGER.merge(deepcopy(self.data[ATTR_OPTIONS]),
                                                deepcopy(self.persist[ATTR_OPTIONS]))
```
Recursive deep merge, user overrides win on scalar conflict, computed live on every access.
([apps/app.py](https://raw.githubusercontent.com/home-assistant/supervisor/main/supervisor/apps/app.py))

**Critical detail**: `write_options()` has exactly one call site — inside `start()`. Saving options
via the API does *not* touch `options.json`. The running container only sees new values on restart.

**On update**: `AppsData.update()` refreshes `system[slug]` from the new `config.yaml` but never
touches `user[slug]`. New defaults appear automatically; **removed keys are never purged** — they
linger forever in `apps.json`, dropped only at validation time with a repeating warning:
`"Option '%s' does not exist in the schema for %s (%s)"`. Cleanup is the add-on author's job via
`bashio::addon.option '<key>'` with no argument.

### (c) Provenance
Weak. No per-field "this is default vs yours" badge — the merge is invisible.

### (d) Read-only config dir
Solved structurally: **`/data` is always mounted, per-add-on, unconditionally writable**,
independent of the `map:` block. Everything else (`homeassistant_config`, `addon_config`, `share`,
`ssl`, `media`, ...) is opt-in and *defaults to read-only*, overridable with `read_only: false`.
This immutable-code + always-writable-per-app-data-dir split is the single most transferable idea.
([add-on configuration docs](https://developers.home-assistant.io/docs/add-ons/configuration))

### (e) How change takes effect
Never automatic. After a successful save, if the add-on is running, the frontend shows a plain
confirm/cancel dialog (`suggestSupervisorAppRestart`). User-initiated, not forced.

### (f) Schema → form
`UiOptions` maps every type onto six `SUPPORTED_UI_TYPES` = `string, select, boolean, integer,
float, schema`. `schema: false` disables validation entirely and forces the **whole** options
object into a raw YAML editor — all-or-nothing, no per-field fallback. Schema language:
`str|bool|int|float|email|url|password|port|match(REGEX)|list(a|b|c)|device`, with `?` suffix for
optional and `(min,max)` ranges. Max nesting depth: 2.

### (g) Complaints
- `PermissionError: /data/options.json` after a 644→600 mode tightening broke non-root add-ons
  ([supervisor#2158](https://github.com/home-assistant/supervisor/issues/2158)).
- Schema too restrictive for free-form config — authors hand-roll `/data` files instead of using
  `schema: false`, suggesting the escape hatch is underdiscovered.
- No first-class way to version-control add-on options; the workaround ecosystem keeps
  reinventing it.

---

## 3. Frigate — UI writes a *subset* of fields back into the user's YAML

The most directly relevant "write back to the config file" precedent, and it does it carefully.

### (a)/(b) Two distinct editors, two distinct write paths
- **Raw Monaco editor** → `POST /config/save?save_option=saveonly|restart`. Validates with
  `FrigateConfig.parse_yaml()` **before** writing, maps each Pydantic error back to a line number
  (`"Line 42: cameras -> front_door -> detect - ..."`), returns 400 without writing on failure.
  Then writes the editor's raw text **verbatim** — so this path cannot mangle comments.
- **Form-based Settings UI** → `PUT /config/set` → `update_yaml_file_bulk()`:
  ```python
  yaml = YAML()          # ruamel round-trip mode
  data = yaml.load(f)    # CommentedMap — comments retained
  for key_path, new_value in updates.items():
      data = update_yaml(data, split_config_key_path(key_path), new_value)
  yaml.dump(data, f)
  ```
  A genuine **ruamel round-trip surgical merge** — targeted key-path mutation, comments on
  untouched regions preserved by construction. There is even a `clear_orphaned_comments()` helper,
  direct evidence they hit and fixed a comment-preservation bug. Writes then **re-validate and
  roll back** to the old raw text on failure.

### (c) Provenance
No file-vs-UI provenance (all paths converge on one file). But it has excellent **global-vs-camera
override** provenance, which is the closer analogue:
> "Frigate treats a camera value as an override because it is written in the config file, not
> because it differs from the global value."

UI surfaces an **Overridden** badge + **Reset to Global** button, a blue dot for
"overrides global", a profile-colored dot for "overridden by active profile", an amber dot for
"unsaved changes", and a per-section count of differing fields.
Merge rule is explicit: **lists replace, maps merge**.
([config_overrides docs](https://docs.frigate.video/configuration/))

There *is* a runtime-vs-YAML ledger but it is **not surfaced**: `/config/.runtime_state.json`
persists MQTT/UI toggles across restarts, replayed at startup through the same handlers. Only
5 topics are tracked (`enabled, detect, snapshots, recordings, audio`). Every *other* dispatcher
toggle (`motion`, `ptz_autotracker`, `improve_contrast`, ...) publishes a retained MQTT message but
is never persisted — so after a restart the MQTT-retained state and Frigate's actual state can
disagree. A real provenance trap.
When a user edits YAML for a field with a tracked override,
`clear_runtime_state_for_yaml_keys()` drops the stale override "so a stale override doesn't
silently win after restart" — exactly the invalidation rule hassette will need.

### (d) Read-only config dir
**No proactive detection.** Editor and Save buttons are always enabled; failure is reactive via a
bare `except Exception` returning
`"Could not write config file, be sure that Frigate has write permission on the config file."`
The one proactive check is in migration, and it *silently skips*:
```python
if not os.access(config_file, mode=os.W_OK):
    logger.error("Config file is read-only, unable to migrate config file.")
    return
```
Frigate then boots against the unmigrated config, producing confusing downstream errors.

### (e) How change takes effect
Per-field `requires_restart` flag on the request body, surfaced in the UI as a restart icon +
"Restart required" tooltip, with a one-click Restart action in the save notification. When
`requires_restart == 0`, `swap_runtime_config()` hot-rebinds the parsed config into the running app
and fans out targeted ZMQ updates per topic, then calls `reapply_runtime_state_to_config()` so a
live-toggled-off camera doesn't silently reappear. The raw editor **never** hot-applies.
This two-tier design is a traceable response to
[discussion #5082 "Config option to SAVE without restart"](https://github.com/blakeblackshear/frigate/discussions/5082).

### (f) Complaints
- **[#13984](https://github.com/blakeblackshear/frigate/discussions/13984)** — "Save Only" emptied
  `config.yml` entirely. Maintainer: "You should check your config file, it is probably empty. I am
  putting up a PR to fix this bug now." Fixed same day.
- **[#14640](https://github.com/blakeblackshear/frigate/discussions/14640)** — a YAML error near the
  end of a long config renders a traceback that blocks the scroll needed to reach the error line.
  User literally cannot fix their own file.
- **[#17131](https://github.com/blakeblackshear/frigate/discussions/17131)** — "Save & Restart" with
  an invalid config shows a perpetual restarting spinner and never restarts.
- **[#11534](https://github.com/blakeblackshear/frigate/issues/11534)** — Kubernetes ConfigMap mounts
  (inherently read-only) can't complete automatic config migration.
- **[#14760](https://github.com/blakeblackshear/frigate/discussions/14760)**,
  [#9529](https://github.com/blakeblackshear/frigate/issues/9529) — read-only filesystem errors.

**Pattern**: almost every shipped bug is UI/error-reporting, not data corruption. The
validate-then-write and write-then-validate-then-rollback mechanics are solid. The recurring
complaint category is **read-only/permission handling**, not comment loss.

---

## 4. AppDaemon — the honest answer: no config UI, none planned that shipped

Closest structural analogue to hassette (Python apps, file-declared args).

- **(a)** `apps.yaml` only. `self.args` is the dict passed to `app_class(self.AD, cfg)` at
  instantiation — **a snapshot, not a live reference**.
- **(b)/(c)** N/A — no UI value exists.
- **(d)** Non-issue: AppDaemon **never writes** `apps.yaml`. Pure input.
- **(e)** `check_app_updates()` polls **mtimes** (not inotify) every second, or only on restart when
  `production_mode: true`. Diffing is per-app (`deep_compare`), so only the changed app reloads —
  via full `terminate()` → `create_app_object()` → `initialize()`. There is **no in-place hot-reload
  of args**; every config change is an app restart, just scoped.
- **(f)** **Confirmed: no config-editing UI.** The Admin Interface is monitoring-only —
  docs say it "is expected to evolve into a full management tool," i.e. still aspirational.
  [#508 "ability to restart apps... from admin interface"](https://github.com/AppDaemon/appdaemon/issues/508)
  filed 2019, **still open**, maintainer: "Restart of apps is planned." The HA add-on ships a
  generic file editor on port 5050 — raw text editing, not structured config.

**The idiomatic workaround is the important finding**: AppDaemon apps that need a runtime-tunable
parameter don't get it from `apps.yaml` at all. They `listen_state()` on an HA `input_number` and
read it with `get_state()`. **Home Assistant, not the framework, is the tunable-value store.**
`self.global_vars` is in-memory only and documented as not threadsafe.
([forum](https://community.home-assistant.io/t/dynamic-offset-from-input-number/76659))

Other complaints: [#585](https://github.com/AppDaemon/appdaemon/issues/585) (one app edit restarted
all apps — mtime/diff granularity bug, now fixed),
[#2509](https://github.com/AppDaemon/appdaemon/issues/2509) (HA restart raced config reload, loading
stale `apps.yaml`).

---

## 5. Node-RED — avoids the conflict by construction

- **(a)** Three-way split: `flows.json` (editor-owned, rewritten on Deploy),
  `flows_cred.json` (encrypted credentials), `settings.js` (operator-owned, loaded once at process
  start, **never editor-editable**).
- **(b)** No runtime conflict exists: `settings.js` holds properties of *the deployment* (paths,
  auth, storage backend); `flows.json` holds properties of *the automation logic*. Letting a flow
  author change the security model of the instance they run in is an operator-only concern by
  design. Env-var refs (`${VAR}`) inside node properties are stored **as the literal reference**
  in `flows.json` and resolved at flow-load — the UI never sees or overwrites the resolved value.
- **(c)** The visible `${VAR}` string *is* the provenance signal. No separate badge.
- **(d)** First-class `readOnly: true` in `settings.js`. Writes are wrapped in
  `if (!settings.readOnly) { ... }` and silently skipped, but the runtime logs plainly at startup:
  `Runtime in read-only mode. Changes will not be saved.` Separately,
  [#3298](https://github.com/node-red/node-red/issues/3298) — with the *filesystem* read-only
  (distinct from the flag), the editor served a blank page; closed as stale without root-causing.
- **(e)** Deploy, with granularity via the `Node-RED-Deployment-Type` header:
  `full` | `nodes` | `flows` | `reload`. Node-RED does **not** watch `flows.json` for external
  edits — the editor is the write path.
- **(f)** `flows.json` is re-serialized as one unformatted line, making git diffs unreadable
  ([#2085](https://github.com/node-red/node-red/issues/2085),
  [#2515](https://github.com/node-red/node-red/issues/2515)); Deploy overwrites unknown fields
  ([#841](https://github.com/node-red/node-red/issues/841)); changing `credentialSecret` silently
  destroys all credentials (documented as a hard warning).

Also: `storageModule` in `settings.js` swaps the entire persistence backend (filesystem → DB) via
the Storage API — a pluggable-persistence precedent.

---

## 6. Zigbee2MQTT — the cautionary tale. Design against this.

The most direct "app writes back to its own YAML" precedent, and the clearest failure.

### (a) Where values live
`data/configuration.yaml`, with optional externalization: `devices: devices.yaml`,
`groups: groups.yaml`. That split exists precisely *because* pairing auto-writes to
`configuration.yaml` while users also hand-edit it, forcing the HA add-on "to somehow merge two
sources of configuration"
([#1148](https://github.com/Koenkk/zigbee2mqtt/issues/1148)).

### (b) Precedence — **confirmed in source, and it's the bug**
`getPersistedSettings()` docstring: *"Get the settings actually written in the yaml. Env vars are
applied on top."* Env wins unconditionally. But `write()` re-applies them **immediately before
persisting**:
```ts
export function write(): void {
  const settings = getPersistedSettings();
  const toWrite = objectAssignDeep({}, settings);
  // ... devices/groups/secret-ref handling ...
  applyEnvironmentVariables(toWrite);              // env clobbers the just-edited object
  yaml.writeIfChanged(CONFIG_FILE_PATH, toWrite);  // ...and THAT is what lands on disk
}
```
So: user edits in the Settings UI → `apply()` → `write()` → every active
`ZIGBEE2MQTT_CONFIG_*` var overwrites the edit → **the reverted value is persisted to disk in the
same write cycle that was supposed to save the user's change**, with no error surfaced.
([settings.ts](https://raw.githubusercontent.com/Koenkk/zigbee2mqtt/master/lib/util/settings.ts))

Independently confirmed from outside:
> "what zigbee2mqtt is doing is reformating configuration.yaml and replacing any values with their
> actual values from the env variables. This happens when you make any kind of change from the UI"
> — [#23589 comment](https://github.com/Koenkk/zigbee2mqtt/issues/23589#issuecomment-2533758922)

### (c) Provenance
**None.** No indicator anywhere distinguishes env-sourced from file-sourced values. This absence is
exactly what makes (b) silent. A user hit this and could only diagnose it by reading source
([#12911](https://github.com/Koenkk/zigbee2mqtt/issues/12911)).

### (d) Read-only config dir
Hard failure, no escape hatch. `EROFS: read-only file system, open '/app/data/configuration.yaml'`
fires **even when** the user has externalized `devices`/`groups` specifically to avoid it, because
`write()` still touches `configuration.yaml` on every settings change, pairing event, or migration.
A v2.0 migration outright refused to start against a read-only ConfigMap mount.
([#23589](https://github.com/Koenkk/zigbee2mqtt/issues/23589)) A dedicated feature request modeled
on Kubernetes ConfigMap conventions went stale and was closed unresolved
([#21803](https://github.com/Koenkk/zigbee2mqtt/issues/21803),
earlier [#2071](https://github.com/Koenkk/zigbee2mqtt/issues/2071)).

### (e) How change takes effect
A custom `requiresRestart` JSON-Schema keyword per property, enforced by **two separate Ajv
compilations** — one normal, one that inverts the keyword:
```ts
const ajvRestartRequired = new Ajv({allErrors: true})
  .addKeyword({keyword: "requiresRestart", validate: (s: unknown) => !s})
  .compile(schemaJson);
```
`apply()` runs changed keys through it and returns a boolean driving a "restart required" indicator.
Restart-required: `mqtt.server`, `serial.port`, `advanced.channel`, `frontend.enabled`.
Hot: `advanced.log_level`, `ota.disable_automatic_update_check`, per-device `optimistic`.

### (f) `!secret` write-back — the one thing it gets right
For 5 hard-coded fields, `write()` writes the *new value through to `secret.yaml`* and puts the
`!secret foo` **reference** back into `configuration.yaml`, preserving the indirection rather than
leaking the resolved secret. Worth copying if hassette ever adds secret refs.

Comment preservation: none. `lib/util/yaml.ts` is a thin js-yaml `load`/`dump` wrapper — a full
parse-and-reserialize from a plain JS object.

---

## 7. Sentry self-hosted — the best complete design found

Not on the original list; surfaced during research. Per-key declared policy, provenance tags, and a
server-computed writability decision.

### (a) Storage
Registered defaults in `options/defaults.py`; disk values in `settings.SENTRY_OPTIONS`
(from `config.yml`); runtime values in a DB-backed `OptionsStore` fronted by local + external cache.

### (b) Precedence — per-key, declared via flags
```python
DEFAULT_FLAGS = 1 << 0
FLAG_IMMUTABLE  = 1 << 1   # Value can't be changed at runtime
FLAG_NOSTORE    = 1 << 2   # Don't check/set in the datastore. Option only exists from file.
FLAG_STOREONLY  = 1 << 3   # Values that should only exist in datastore, not in config files.
FLAG_REQUIRED   = 1 << 4
FLAG_PRIORITIZE_DISK = 1 << 5  # If the value is defined on disk, use that and don't fetch from db.
                               # This also make the value immutable to changes from web UI.
FLAG_ALLOW_EMPTY = 1 << 6
FLAG_CREDENTIAL  = 1 << 7  # Values that are credentials should not show up in web UI.
FLAG_ADMIN_MODIFIABLE     = 1 << 8
FLAG_AUTOMATOR_MODIFIABLE = 1 << 11
```
`get()` resolution order: read hook → disk (only if `FLAG_PRIORITIZE_DISK`) → DB store →
default (`SENTRY_OPTIONS` → `SENTRY_DEFAULT_OPTIONS` → registered default).

**Default behavior (no flags): the DB value wins and the file is only a seed/default.**
`FLAG_PRIORITIZE_DISK` inverts that per key. This per-key opt-in is the key idea.

Operator docs state it as an intentional escape hatch:
> "for all new-style config (as of 8.0) you can also declare values in the config file to enforce
> defaults or to ensure they cannot be changed via the UI"
([develop.sentry.dev](https://develop.sentry.dev/backend/application-domains/options/))

### (c) Provenance — two mechanisms
1. Every `get()` records `tags["source"]` ∈ `{"hook", "disk", "store", "default"}`.
2. `can_update(key, value, channel) -> NotWritableReason | None`:
```python
class NotWritableReason(Enum):
    OPTION_ON_DISK = "option_on_disk"        # FLAG_PRIORITIZE_DISK + present in settings
    READONLY = "readonly"                     # FLAG_NOSTORE or FLAG_IMMUTABLE
    CHANNEL_NOT_ALLOWED = "channel_not_allowed"
    DRIFTED = "drifted"
```
The **API returns a structured triple per field**, so the client never guesses
([system_options.py](https://github.com/getsentry/sentry/blob/master/src/sentry/api/endpoints/system_options.py)):
```python
"field": {"default": k.default(), "required": ..., "disabled": disabled,
          "disabledReason": disabled_reason, "isSet": options.isset(k.name),
          "allowEmpty": ...}
```
Frontend maps the code to copy
([options.tsx](https://github.com/getsentry/sentry/blob/master/static/app/views/admin/options.tsx)):
```tsx
const disabledReasons = {
  diskPriority: 'This setting is defined in config.yml and may not be changed via the web UI.',
  smtpDisabled: 'SMTP mail has been disabled, so this option is unavailable',
};
```
Write attempts that violate policy raise
`"%r cannot be changed at runtime because it is configured on disk"`, surfaced as
`error: "immutable_option"`.

**One decision function feeds two surfaces** — the same `can_update()` backs the REST endpoint and
a CLI presenter with `DRIFT_MSG = "[DRIFT] Option %s drifted and cannot be updated."`. Directly
relevant given hassette has both a CLI and a web UI.

### (d)/(e) Consistency
`OptionsStore.get()`: local cache → external cache → DB. `DEFAULT_KEY_TTL = 10`s,
`DEFAULT_KEY_GRACE = 60`s. Cross-process propagation ~10s. Docstring is explicit that this is
eventually consistent by design.

### (f) Complaints
[sentry#12722](https://github.com/getsentry/sentry/issues/12722) — a fresh install threw
`AssertionError: 'mail.port' cannot be changed at runtime because it is configured on disk` from the
setup form: a raw crash instead of a clean error. The exact collision hassette must handle
gracefully. Later versions return the structured `immutable_option` error instead.

### Overkill for hassette
`UpdateChannel` / `FORBIDDEN_TRANSITIONS` exists to stop a GitOps automator clobbering human
changes across hundreds of options and many writers. Verbatim, the only forbidden direction is
*any channel → AUTOMATOR*. hassette has one write channel (the UI) plus the file, so the transition
matrix collapses. Likewise most of the flag taxonomy — a `locked_to_file: bool` plus
`sensitive: bool` probably covers it.

---

## 8. systemd drop-ins — the best provenance *display* model

- **Precedence**: `/etc/systemd/system` > `/run/systemd/system` > `/usr/lib/systemd/system`
  (vendor, package-owned). "Unit files found in directories listed earlier override files with the
  same name in directories lower in the list."
  ([systemd.unit(5)](https://manpages.debian.org/testing/systemd/systemd.unit.5.en.html))
  Caveat: drop-in ordering across those dirs is a known ambiguity
  ([systemd#13198](https://github.com/systemd/systemd/issues/13198)).
- **Merge**: "All files with the suffix `.conf` from this directory will be merged in the
  alphanumeric order and parsed after the main unit file itself has been parsed." Key-by-key for
  scalars; **additive** for list-valued settings, with the empty-assignment reset trick
  (`ExecStart=` then `ExecStart=/new`).
- **Provenance**: `systemctl cat UNIT` — "Prints the 'fragment' and 'drop-ins' (source files) of
  units. **Each file is preceded by a comment which includes the file name.**" Every effective
  config line is traceable to a specific file, inline, in the same merged view a human reads to
  understand current behavior. `systemd-delta` classifies units as `masked`, `equivalent`,
  `redirected`, `overridden`, `extended`, `unchanged`.
- **Never touch the vendor file**: `systemctl edit` writes a *new* drop-in; `systemctl edit --full`
  is the explicit escape hatch that copies the vendor unit into `/etc`.

**Transferable**: the never-write-the-original + per-line source attribution model.
**Overkill**: three-tier search path, lexicographic multi-file drop-in ordering, masking.

---

## 9. django-constance — the staleness trap, in Python, confirmed in source

Closest library-level analogue: settings declared in code with defaults, overridable at runtime from
an admin UI, persisted in a DB/Redis backend.

Declaration: `CONSTANCE_CONFIG = {'THEME': ('light', 'Theme for the site.', str)}`.

**Precedence** ([base.py](https://github.com/jazzband/django-constance/blob/master/constance/base.py)):
```python
def _get_sync_value(self, key, default):
    result = self._backend.get(key)
    if result is None:
        result = default
        setattr(self, key, default)   # writes the default INTO the backend on first read
    return result
```
The stored value wins unconditionally whenever non-`None`. No comparison against the current
declared default, no versioning, no timestamp. **And the default is written into the backend on
first read** — so from the very first access, the value in `CONSTANCE_CONFIG` is dead for that key.
Changing the declared default later has zero effect.

- [#535 "Allow modifying defaults"](https://github.com/jazzband/django-constance/issues/535) —
  **closed as not planned**. The project's official position is that this staleness is permanent
  behavior, not a bug.
- [#348](https://github.com/jazzband/django-constance/issues/348) — `DatabaseBackend.get()` swallows
  `OperationalError`/`DoesNotExist` and returns `None`, which the fallback misreads as "never set"
  and **writes the default back**, silently resetting a real stored value on a *transient DB error*.

Reads hit the backend on every access unless `CONSTANCE_DATABASE_CACHE_BACKEND` is configured.
Orphaned keys are never auto-cleaned; there is a manual
`constance remove_stale_keys` management command.

**dynaconf** (non-Django alternative) does track provenance — `SourceMetadata` per key, surfaced via
`dynaconf inspect` (loader type + file path + env + value, newest-first). Its write-back
(`toml_loader.write(path, data, merge=True)`) targets **one explicitly-named file** (it has no
concept of "the layer this key came from"), defaults to `merge=False` which silently overwrites the
whole file, and does not preserve comments.

**The lesson for hassette**: if a UI-set value shadows the file value, decide explicitly what
happens when the *file* value later changes. constance's answer (file default is permanently dead)
is a documented, deliberate, and widely-complained-about trap.

---

## 10. Grafana — the most refined provenance model, and the loudest complaints

### Settings layering
`defaults.ini` → `grafana.ini`/`custom.ini` → `GF_<SECTION>_<KEY>` env vars → CLI flags (highest).
Env transform: uppercase, `.` and `-` → `_`. Value expansion: `$__env{VAR}`, `$__file{/path}`,
`$__vault{...}`. `/api/admin/settings` returns the **effective merged** view — a read model over the
precedence chain, not a separate source of truth.

### Provisioning provenance
Datasources use `editable: false`. Exact frontend string
([DataSourceReadOnlyMessage.tsx](https://github.com/grafana/grafana/blob/main/public/app/features/datasources/components/DataSourceReadOnlyMessage.tsx)):
> "This data source was added by config and cannot be modified using the UI. Please contact your
> server admin to update this data source."

Dashboards use `allowUiUpdates`. The load-bearing rule, verbatim from the docs:
> "If you save a provisioned dashboard in the UI and then later update the provisioning source,
> Grafana always overwrites the database dashboard with the one from the provisioning file."

So UI edits under `allowUiUpdates: true` are a **temporary override, not a merge or a fork**.

### Alerting — the explicit provenance field
```go
type Provenance string
const (
    ProvenanceNone Provenance = ""
    ProvenanceAPI  Provenance = "api"
    ProvenanceFile Provenance = "file"
    ProvenanceConvertedPrometheus Provenance = "converted_prometheus"
)
```
Non-`none` provenance locks the resource; docs: "Provisioned resources are labeled Provisioned, so
that it is clear that they were not created manually." The `X-Disable-Provenance: true` header lets
an API write land as `provenance = none` (UI-editable) — but **not for file provenance**, which is
unconditionally exclusive ([#99564](https://github.com/grafana/grafana/issues/99564)).

### The generalization Grafana is migrating to (most transferable artifact)
`pkg/apimachinery/utils/manager.go` replaces the flat enum with a full manager identity:
```go
type ManagerProperties struct {
    Kind        ManagerKind  // repo | terraform | kubectl | plugin | grafana | classic-* shims
    Identity    string       // specific instance of the manager
    AllowsEdits bool
    Suspended   bool
}
type SourceProperties struct {
    Path            string  // file path, URL
    Checksum        string  // e.g. git commit hash
    TimestampMillis int64   // e.g. file mtime
}
```
Grafana's own doc comments frame the old three-value enum as a lossy legacy shim. That is: a mature
project that shipped `provenance: file|api|none` concluded it was too coarse and is replacing it
with named owners + an edit-allowance flag + sync metadata. **If hassette starts with a
provenance enum, this is the known upgrade path.**

### Complaints — the clearest signal in the whole survey
[#11778 "Allow UI to save changes for provisioned dashboards"](https://github.com/grafana/grafana/issues/11778),
filed 2018, **still open**. @torkelo:
> "the new provision workflow enforces automation... provisioning enforces saved changes to
> dashboard to go through provisioning so you always know what is the correct & latest state ...
> But I agree, maybe an option in provisioning to 'allow UI save' is worth considering if that is
> what many users want."

That became `allowUiUpdates` — but the file still wins on reload, so the complaint never went away.
A commenter: *"since I cannot save provisioned dashboards, the export is useless since it doesn't
contain unsaved changes."*

Grafana then **re-litigated the identical tension in Alerting years later**
([#57314](https://github.com/grafana/grafana/discussions/57314),
[#57315](https://github.com/grafana/grafana/issues/57315),
[#57911](https://github.com/grafana/grafana/issues/57911),
[#92454](https://github.com/grafana/grafana/issues/92454)) — same ask: "let me tweak a provisioned
rule in the UI and export the result back to code."

Bypass bugs undermine trust in the lock:
[#32556](https://github.com/grafana/grafana/issues/32556) (readonly datasource editable via raw API
PUT), [#37679](https://github.com/grafana/grafana/issues/37679) (provisioned dashboard editable via
the JSON Model tab despite `allowUiUpdates: false`),
[#25406](https://github.com/grafana/grafana/issues/25406) (users assume `editable: false` is a full
write lock; it's a UI-only guard).

**Distilled**: (1) the lock is binary where users want graduated trust; (2) "file wins on next
reload" silently discards UI work with no diff at the moment of loss; (3) enforcement is
inconsistent across resource types, so the mental model doesn't transfer.

---

## 11. Others, briefly

### Paperless-ngx — cheapest good provenance UX
DB `ApplicationConfiguration` **overrides** env/file. Source
([config.py](https://github.com/paperless-ngx/paperless-ngx/blob/main/src/paperless/config.py)):
```python
self.language = app_config.language or settings.OCR_LANGUAGE
self.deskew = app_config.deskew if app_config.deskew is not None else settings.OCR_DESKEW
```
Note the explicit `None`-check for booleans so a stored `False` isn't treated as unset — a real trap
worth copying. Provenance is not a per-field badge; instead the page header states the rule once:
> "Options can also be set using environment variables or the configuration file but the value here
> will always take precedence."

and each overridden field grows a **Reset** button that appears only when a DB value exists.
DB-stored, so a read-only config mount is a non-issue. Applies immediately.
Deliberately scoped to "common OCR related settings and some frontend settings" —
not a general mechanism for every env var
([PR #5126](https://github.com/paperless-ngx/paperless-ngx/pull/5126)).

### Immich — binary switch, enforced server-side
File XOR DB, never both, and the enforcement is in the API route, not just the UI:
```ts
if (configFile) {
  throw new BadRequestException('Cannot update configuration while IMMICH_CONFIG_FILE is in use');
}
```
Also worth stealing: a startup **log-line provenance** pattern —
```ts
this.logger.log(`LogLevel=${level} ${envLevel ? '(set via IMMICH_LOG_LEVEL)' : '(set via system config)'}`);
```
No file hot-reload — editing the file requires a restart, since the cache is only invalidated by the
`ConfigUpdate` event, which only fires on the (blocked) DB path.
Complaints: [#12408](https://github.com/immich-app/immich/discussions/12408) — users want settings
*not* covered by the file to stay UI-editable (a partial/merged mode Immich refuses);
[#10344](https://github.com/immich-app/immich/issues/10344) — can't test SMTP from the UI because
the *whole* settings surface locks, not just the relevant field.

### Nextcloud `config_is_read_only` — the deadlock cautionary tale
A first-class read-only-config mode:
> "When this switch is set to `true`, writing to the config file will be forbidden. Therefore, it
> will not be possible to configure all options via the Web interface."

But it's blunt: it also blocks `occ` (the CLI) and the **upgrade path**, which itself needs to write
`config.php`. Real incident: neither the web UI nor `occ` could proceed until the admin hand-edited
the mounted file to flip the flag. Docs concede: "when updating Nextcloud, it is required to make
the configuration file writable again and to set this switch to `false`."
**Lesson**: a read-only-config mode needs an explicit, documented exception for the app's own
internal/migration writes, or first boot against a read-only mount hard-fails.
([docs](https://docs.nextcloud.com/server/stable/admin_manual/configuration_server/config_sample_php_parameters.html),
[incident](https://help.nextcloud.com/t/config-is-set-to-be-read-only-via-option-config-is-read-only/138671),
[#29901](https://github.com/nextcloud/server/issues/29901))

### Authentik blueprints — per-object precedence, not a global mode
Per-entry `state:` field:
- `present` (default) — updates the fields in `attrs` on every reapply; blueprint always wins,
  silently overwriting UI edits.
- `created` — **"Creates the object if it doesn't exist, but never updates it afterward. Manual
  changes are preserved."** File seeds once, then UI owns it permanently.
- `must_created` — fails the apply if the object already exists.
- `absent` — deletes.

Objects are matched by an `identifiers:` block separate from the `attrs:` being written — the
identifier is how the importer finds "the same logical object" across reapplies. Directly relevant:
hassette app config is a *list* of instances keyed by `instance_name`, so overrides need a stable
identifier, not a list index.
([docs](https://docs.goauthentik.io/customize/blueprints/v1/structure/))
Provenance UI text is unconfirmed — flag as a gap.

### Traefik — partition the config space instead of arbitrating
Static config (entrypoints, providers, cert resolvers) is file/CLI/env only and **requires restart**.
Dynamic config (routers, services, middlewares) is provider-sourced and hot-reloaded with
`watch: true`. Since the two layers configure **disjoint concerns**, there is no "which wins"
question to display at all. Suggests shrinking hassette's precedence problem by declaring some
fields permanently file-only.

### Uptime Kuma / Sonarr / Radarr — the negative signal
Uptime Kuma: everything in SQLite, no app config file; env vars are bootstrap-only. Sustained,
unresolved complaints from automation-minded users:
[#3578 "FR: Config File"](https://github.com/louislam/uptime-kuma/issues/3578) (2023, still cited),
[#6045](https://github.com/louislam/uptime-kuma/issues/6045),
[#855](https://github.com/louislam/uptime-kuma/issues/855) ("installing the software is easy,
actually configuring Uptime Kuma is more problematic" — from an Ansible user),
[#7369](https://github.com/louislam/uptime-kuma/issues/7369).
Radarr [#11425](https://github.com/Radarr/Radarr/issues/11425) ("Configure settings externally")
was **closed as "not planned"** — DB-only-by-design is a deliberate maintainer stance some projects
take, and IaC pushback doesn't always win.

**Read this as confirmation that hassette's file-first default is correct** — pure DB-only config
draws sustained complaints. The design question is only how to add a *second* writable layer.

### ESPHome dashboard
YAML on disk, browser editor writes straight back, `!secret` indirection. No hot-reload concept at
all — "saving a configuration does not change the physical device... you need to click **Install**".
Read-only-mount behavior unconfirmed (coverage gap).

### Kubernetes SSA — transferable diagnosis, overkill cure
`metadata.managedFields` tracks **per-field** ownership (manager + operation + timestamp), not
per-object. Conflicts are rejected unless `force: true`; the error names the exact field path.
The three-way resolution menu is a clean, reusable UX framing: **force-overwrite / relinquish your
claim / adopt the other value**. The *problem statement* behind SSA replacing
`last-applied-configuration` — "can't distinguish field omission from field removal, and there's no
record of who owns what" — is precisely the "user edited the TOML, then edited in the UI, now what?"
question. The machinery is disproportionate for a single-user framework; the diagnosis is not.
ArgoCD's `ignoreDifferences` (per-field declared drift exemption) is the lightweight analog; a
passive "drift detected, here's the diff" surface is likely right-sized versus auto-revert.

---

## Cross-cutting synthesis

### On persistence (the read-only mount question)
**The problem largely dissolves if you don't write the TOML.** Every system that keeps overrides in
a separate store (systemd drop-ins, HA `.storage`, add-on `apps.json`, Sentry DB, constance DB,
Paperless DB, Immich DB) has no read-only-mount story to tell, because the config file is
permanently input-only. Every system that rewrites the user's file (Z2M, Frigate, Node-RED,
ESPHome, Nextcloud) has an open read-only-mount issue.

hassette already has the right substrate: `data_dir` defaults to `/data` (Docker convention),
separate from `config_dir` (`/config`), already holds the telemetry SQLite DB and per-app cache DBs
at `data_dir/<cache_key>/cache/cache.db`. This is structurally identical to the HA add-on
`/data` vs `/config` split.

If write-back to TOML is ever wanted anyway, Frigate's `update_yaml_file_bulk()` is the reference
implementation: ruamel round-trip, surgical key-path mutation, re-validate, roll back on failure —
and even then, add a proactive writability check rather than Frigate's reactive `except Exception`.

### On precedence
Three viable models, in increasing order of sophistication:

| Model | Example | Fit |
|---|---|---|
| Global XOR — file present ⇒ UI fully locked | Immich | Simplest; but complaints show users want partial |
| Per-key policy flag | Sentry `FLAG_PRIORITIZE_DISK` | Best balance; opt-in lock per field |
| Per-object reconcile state | Authentik `present` / `created` | Most expressive; `created` = "file seeds once, UI owns after" |

The recurring complaint across Grafana, Immich, and HA is that a **binary/global** lock is too
coarse. Both Sentry and Authentik solve it at the granularity users actually want.

Whatever the choice, the decision must be **server-enforced, not UI-only**. Grafana's read-only
guard was UI-only, and users routinely bypassed it via raw API PUT
([#32556](https://github.com/grafana/grafana/issues/32556),
[#37679](https://github.com/grafana/grafana/issues/37679)) — which then undermined trust in the
feature. Immich enforces in the route handler; Sentry enforces in `can_update()`.

### On provenance
The API contract and the display are separate problems with separate best answers:
- **API**: Sentry's per-field `{value, disabled, disabledReason, isSet, default}`. Server decides;
  client never guesses. One `can_update()` serving both CLI and REST.
- **Display**: `systemctl cat`'s inline source attribution is the gold standard. Paperless's
  Reset-button-when-overridden is the cheap version that still works. Frigate's
  Overridden badge + Reset to Global + colored dots is the middle ground.
- **Free win**: Immich's startup log line naming *why* a value is what it is.
- **Anti-pattern**: Z2M shows nothing, which is what makes its silent revert undetectable.

Also: HA's inconsistent per-panel strings are a warning. Write the provenance component once.

### On how the change takes effect
Two proven granularity mechanisms:
- A per-field `requires_restart` declaration surfaced in the UI, with hot-apply for the rest
  (Frigate, Z2M's `requiresRestart` JSON-Schema keyword).
- An explicit user-confirmed restart prompt scoped to the affected unit (HA add-ons'
  `suggestSupervisorAppRestart`).

Nothing in this survey auto-restarts silently. Every system either hot-applies or asks.

For hassette specifically, `AppChangeDetector` already distinguishes `reload_apps` (config changed)
from `reimport_apps` (code changed), which is exactly the granularity needed — a UI-set value should
produce a `reload_apps` reconcile for one app, not a framework restart. Note that the file-watcher
path is currently gated on `dev_mode or allow_reload_in_prod`, so "takes effect without restart" in
production cannot rely on the existing watcher as-is.

### On invalidation — the question nobody answers well
When a UI override exists and the *file* value later changes, what happens? Answers found:
- constance: file default is permanently dead. Closed as not planned. Widely complained about.
- Grafana: file wins back on next reload, silently, no diff shown. Most-complained-about behavior
  in the entire survey.
- Frigate: `clear_runtime_state_for_yaml_keys()` — editing the YAML for a field with a tracked
  override **drops the override**, "so a stale override doesn't silently win after restart."
- HA add-ons: never resolved; removed schema keys linger in `apps.json` forever, warning on
  every start.

**Frigate's rule is the only one that isn't a documented pain point.** It's also the most
intuitive: touching the file is an explicit statement of intent that reclaims the key.

### Open questions this survey cannot answer
- **Identity for overrides.** hassette app config can be a *list* of instances
  (`[[hassette.apps.motion_lights.config]]`) with `instance_name` auto-generated as
  `{class_name}.{idx}` when unset. An override keyed by list index breaks on reorder. Authentik's
  `identifiers:` block is the shape of the answer, but the key choice is a hassette decision.
- **Whether to expose overrides as HA entities instead.** AppDaemon's community converged on
  `input_number` + `listen_state` — HA becomes the tunable-value store, and hassette writes no
  config at all. For the OrangeTheory class-time example this may be a genuinely simpler answer
  than building a config-override layer. Worth costing before committing.
- **Cross-process consistency.** Not investigated for hassette's process model. Sentry's
  10s TTL / 60s grace is one calibration point.

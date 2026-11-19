# Research Brief: hassette's persistence model, from a clean slate

```yaml
proposal: "Decide hassette's persistence model: which lifecycle classes of data it keeps, what each promises the user, what format and store each lives in, how each recovers, and whether user apps get a durable store. Builds on the 2026-11-19 durable-state-vs-telemetry brief rather than redoing it."
date: 2026-11-19
status: Draft (revised after challenge, 2026-11-19)
flexibility: Exploring
motivation: "The prior brief's recommendation (a second SQLite file ATTACHed to DatabaseService) was partly shaped by current code and ratified spec text. Re-weigh the bigger change on its merits: independent stores, JSON vs SQLite for owned state, and one general owned-state primitive vs one-off tables."
constraints: "Framework with user apps in other repos; solo dev; pre-v1 (clean breaks, no compat shims); small installs; HA-facing design follows HA conventions unless there's a strong reason. Ratified specs 110/129/132/155/157 and existing code are changeable. Name their cost; don't treat them as decisive."
non-goals: "Retention priorities; HA-side (hass-hassette) behavior; implementing anything."
depth: deep
```

**Initiated by:** a follow-up to issue #4277. The user reviewed the prior brief (`design/research/2026-11-19-durable-state-vs-telemetry/research.md`) and asked for a clean-slate pass on three points: ATTACH vs independent stores, JSON vs SQLite for owned state, and one owned-state primitive vs one-off tables. An adversarial challenge of the first draft then asked for the owned-state decision to be split, the recovery policy to be set per store, and the versioning, codec and deletion rules to be made precise. This version is the result.

## Bottom line

hassette should keep observed and owned data in separate, independent files. It should build owned state on the SQLite key-value store it already has, not on a new JSON primitive.

1. **Observed data stays in `hassette.db`**: telemetry, registrations, and spec 132's projections. It can be regenerated, so a bad or too-new file is moved aside and replaced, as HA's recorder does.
2. **The app-facing store is `self.cache`, hardened in place.** It is already an independent SQLite file per `cache_key` with a sync facade, row-level writes, and safe sharing across instances and processes. Four fixes make its documented durability true:
   - A corrupt or too-new file is left in place, and the instances using it refuse to start, instead of the file being deleted.
   - Values are JSON-native, checked at `set()`, instead of pickled.
   - One store object serves each file (#2748).
   - Backups snapshot it.
3. **Framework owned state** (entity declarations and values, config overrides) gets its own SQLite file, `hassette-state.db`, built on the same hardened file layer. It holds one JSON document per instance. It goes neither in `hassette.db` nor in JSON files.
4. **Recovery is decided per consumer.**
   - Entity and app stores refuse their instances when the file is corrupt or too new. The file is untouched, the instance is `FAILED` with a reason, and health turns CRITICAL.
   - Overrides fall back to the user's file config and refuse writes.
   - Versions are a single integer, and a newer file is never written.
   - Recovery code never deletes owned data. The startup prune becomes a 30-day tombstone.
   - There is no group commit. Spec 157 D10 applies as written.

**Verdicts on the three original points:**

- **(1) Independent stores, not ATTACH.** This holds on a clean slate, unchanged from the draft.
- **(2) SQLite, not JSON, for owned state.** This reverses the draft. JSON's four advantages didn't survive scrutiny:
  - Rollback through minor versions isn't write-safe (HA re-stamps the file and drops unknown fields).
  - Backup consistency stops being an advantage once app stores need a snapshot anyway.
  - Hand-editing works only with hassette stopped.
  - "HA convention" is about an internal file format, which CLAUDE.md's HA-convention rule doesn't cover.

  On the other side, the app store needs what SQLite already provides: sync-thread access, sharing across instances and processes, and per-row writes.
- **(3) One shared file layer, not one shared store.** Each client owns its document shape and write policy. There is still no separate disposable-cache class.

**Cost:** medium overall, smaller than the draft's "large". There is no new storage technology and no JSON file module. The work is a hardening of `src/hassette/cache/`, a status registry with health surfacing, a second SQLite file for framework state, and a snapshot command for backups. The breaking change for apps is the value contract: JSON-native only, plus a one-time reset of pickled entries.

## Revision after challenge (2026-11-19)

The challenge (21 findings, `mine-challenge` run on the first draft) changed these things. The observed/owned split and store independence weren't disputed and stand.

| Findings | What changed |
|---|---|
| 1, 5, 6, 13, 14, 20 (one primitive; hardening `AsyncCache` never evaluated) | Verdict 3 is split into 3a (framework store) and 3b (app store). Hardening `AsyncCache` is evaluated and chosen for 3b. The framework store then reuses its file layer, so what's shared is that layer only. The claim that the change "adds no new public API" is withdrawn, because the value contract changes. The sync facade, per-path sharing and cross-process access stay solved by SQLite. Whole-document rewrite cost no longer applies to the app store. |
| 12 (JSON arguments overweighted) | Verdict 2 is re-weighed and reversed for both stores. |
| 2, 8, 10, 15 (start-empty recovery policy) | Replaced by a per-consumer policy: refuse for entity and app stores, file-config fallback for overrides, and a defined unit of corruption. The health signal is now part of the design. |
| 4, 11, 18 (major/minor versions) | Replaced by a single integer version that refuses newer files, plus a narrow owned schema so bumps stay rare. HA's re-stamp on a minor mismatch was verified in its source. |
| 7 (codec silently changes types) | The codec is now a gate: values must be JSON-native, checked at `set()`. Every stored corpus type was checked against the rule. |
| 9 (deletion contradicts spec 157) | The rule is restated. The instance prune becomes a 30-day tombstone, as HA does for deleted entities. Orphaned app-store files are listed in health and never deleted. |
| 3, 16, 17 (group commit) | Dropped. Spec 157 D10 applies as written. If writes prove too slow, relaxing the sensor promise is the lever. |
| 19 (cross-store consistency) | Closed with authority rules. |
| 20, 21 (store size; fsync on unusual filesystems) | Recorded as accepted limitations. |
| LI-1 | No change. Those follow-ups were already separate. |

## What this pass changes from the prior brief

- **The prior brief's peer row was wrong.** It said "AppDaemon and pyscript persist nothing" (`research.md:101`). Both persist:
  - AppDaemon has user-defined namespaces saved to a `shelve` (dbm) file. `safe` mode syncs on every write; `hybrid` syncs every 1 s.
  - pyscript has `state.persist()` for `pyscript.*` entities, riding HA's `restore_state`.
  - NetDaemon v2 had a JSON `SaveData`/`GetData` store, and v3 dropped it.
- **The prior brief scoped the cache out as a non-goal.** The cache is where most real durable state already lives, so the persistence model can't leave it out.
- **The prior brief's recommendation (Option B, ATTACH) is superseded.** What replaces it is close to the independent-SQLite alternative that brief considered, reshaped. It holds documents instead of typed columns, and its file layer is shared with the hardened cache.

## The lifecycle classes

| Class | Home | Survives restart and upgrade | Too-new file (rollback) | Corrupt file | Deleted only by | Backup |
|---|---|---|---|---|---|---|
| **Observed** (telemetry, registrations, projections) | `hassette.db`, SQLite (unchanged) | Yes; migrated forward | Today `SchemaVersionError`. Proposed: moved aside, fresh file, history lost | Moved aside, fresh file, WARNING (HA recorder) | Retention; the user | Excluded from add-on backups by default (decided 2026-11-19, like HA's `exclude_database`) |
| **Owned, framework: entities** (declarations, switch and sensor values and attributes) | `hassette-state.db`, one row per instance holding a JSON document | Yes; durable when `set()` returns (`synchronous=FULL`) | File untouched; instances that declare entities go `FAILED` until upgrade or restore | Left in place; those instances go `FAILED`; CRITICAL health | The app no longer declaring a key (D6/D9); the instance prune, as a 30-day tombstone | Snapshot command |
| **Owned, framework: overrides** (#2768) | `hassette-state.db`, own table, one row per instance | Yes | Overrides unavailable: file config applies, override writes raise | Same as too-new; CRITICAL health | The user clearing an override | Snapshot command |
| **Owned, app** (`self.store`, renamed from `self.cache`) | `data_dir/<cache_key>/cache/cache.db` (unchanged path) | Yes; durable when `set()` returns | File untouched; every instance sharing it goes `FAILED` | Left in place; sharing instances go `FAILED`; CRITICAL health | The app (`delete`, `clear`, its own TTL); the user deleting the file. Never recovery code | Snapshot command |

There is no separate **rebuildable cache** class. HA has none at the integration level either: ESPHome's HA-side "cache" is an ordinary `Store` it tolerates losing (`components/esphome/entry_data.py:605-655`). A TTL entry in the app store is a cache entry. The corpus has 3 true-cache uses against about 24 durable-state uses.

### Where every item goes

| Item | Class | Notes |
|---|---|---|
| `executions`, `log_records`, `blocking_events`, `api_writes`, `listener_misses`, `lifecycle_events`, `sessions` | Observed | Unchanged. The prior brief's classification stands. |
| `listeners`, `scheduled_jobs`, `app_manifests` | Observed (registration identity) | Losing them changes CLI ids and loses grid history only. |
| Spec 132's `app_runtime`, `app_instances`, `service_status`, `session_counters` | Observed (projection) | Unchanged. |
| #2768 per-session effective config and provenance | Observed (projection) | Session-scoped, rebuilt at app creation. |
| #1753 failsafe stats row, if built | Observed | |
| **Spec 155/157 entity declarations plus switch and sensor values and attributes** | **Owned, framework** | One document per instance. D9's replace-the-set is one row upsert. |
| **#2768 config overrides** | **Owned, framework** | A raw `field → value` map per instance, validated against the app's config model when applied. HA's model is a config entry's `options`. |
| **App state (`self.cache` today)** | **Owned, app** | Hardened in place (decision 3b). |
| `.web_api_token` | Owned, framework | A temp-file-and-rename file with no fsync (`src/hassette/web/auth/tokens.py:151-170`), regenerated if missing. A lost token only forces a re-pair, so leave it. |
| App-written files in `data_dir` (JSONL logs, frame archives, a library's session pickle) | App's own business | Out of scope. `data_dir` is documented as persistent (`docs/pages/core-concepts/configuration/index.md:118`). |

### Sensor values and the "restore" question

HA treats an entity's last value as a **restore cache**. `core.restore_state` is rewritten every 15 minutes and at stop, and entries expire after 7 days (`helpers/restore_state.py:30-33, 341-369`). pyscript and `hass-variables` inherit that. Spec 155 D6 chose a stronger promise for hassette: a value is committed before it is published, for switches and sensors alike.

On a clean slate the strong promise fits switches, which hold user-commanded desired state. For sensors it is optional, because a sensor value lost in a crash is republished on the next `set()`. Spec 157 D13 already makes an identical `set()` a no-op, so only *changing* values cost a commit. This brief keeps the strong promise for both. If the prototype shows per-commit latency hurting at realistic rates, relaxing sensors to restore-class is the lever (needs-user, below), not batching.

## Evidence: the real-user corpus (`~/source/hautomate/`)

Paths are under `src/hautomate/`.

- **Scale:** 42 `App` subclasses, 24 of which touch `self.cache`. About 120 call sites cover about 45 distinct entries.
- **Classification of the distinct entries:**
  - 3 are a true cache: the thermoscura sensor fallback, the OTF schedule fingerprint, and Monarch `max_update`.
  - About 18 are dedup or rate-limit memory: the notify throttle in 8 apps, car_climate's remote-start dedup, and thermoscura's notification cap.
  - About 24 are durable app state, where losing the value changes behavior.
- **Only 8 call sites set a TTL.** Everything else is stored forever and overwritten or deleted by the app.
- **Apps rely on the cache surviving restarts and deploys.** Examples:
  - `desk_stand_nudge.py:23`: "Kept across restarts so a break spanning one still counts."
  - `porch_lights.py:96`: "Override still in effect after restart".
  - `dryer_humidity.py:134`: `resume_cycle` exists only to pick the cycle up after a restart.
  - `announcer.py:390,406`: held announcements must play after a restart.
  - `meeting_app.py:141`: "No cached restore states found -- snapshotted %d lights (may contain meeting colors)". This is wrong behavior when the state is lost.
  - `car_climate.py:374,613` (2 h TTL): a restart mid-class could double-start the car if the dedup key were lost.
- **Deploys land on top of running state.** The consolidation audit (`design/audits/2026-11-01-consolidation/synthesis.md:195`) found a crash triggered by a restart into persisted `ended_at`. With "pull_policy: always", deploys and rollbacks are routine.
- **The app author hardened against pickle.** They store versioned plain dicts so "a class rename can't break unpickling" (`travel_status/app.py:349`, `bedtime_state.py:22`, `announcer.py:61`). ISO strings from `format_iso()` are the norm for times. Four entries still depend on pickle's exact round trip (see the codec section).
- **Cross-app sharing is real.** Six apps share `cache_key = "household"` with `cache_shared = true`, and two share a Bluelink token (`config/hassette.toml:545,560-562`). The rationale is atomic multi-field state with no HA round trip (`design/specs/004-bedtime-state-and-steps/design.md:48-69`). That spec also accepts "a corruption reset of the shared SQLite file can split the five apps' caches", which is open hassette issue #2748.
- **API gaps the author worked around:**
  - No key listing: `announcer.py:56-57` says "One cache entry rather than one per key, because the cache can't list its keys".
  - No multi-key transaction: diskcache's `transact()` was dropped in migration commit `cdaaaa8`.
- **HA helpers used deliberately as storage:**
  - `trackers.py:3` keeps last-done dates in `input_datetime` because HA "keeps [it] across restarts and [it] can still be edited by hand". That is an edit in HA's UI, not a file edit.
  - Monarch moved about 30 values from `set_state` sensors to `input_number` helpers to survive HA restarts (commit `c21d9ea`).
- **Searched and not found:** shelve, sqlite or pickle files written by apps, and apps reading HA history or the logbook at startup to rebuild memory. Patterns searched: `self\.cache|cache=`, `open\(|json\.(dump|load)|pickle|shelve|sqlite`, and `get_history|logbook|lost on restart|persist`.

**Inferred:** the corpus is one power user's apps, written by Claude, so it shows usage, not demand. It is still the only evidence, and it unanimously treats `self.cache` as durable app storage.

## Evidence: what hassette promises today

- **The docs promise durability.** `docs/pages/core-concepts/cache/index.md:3`: "`self.cache` stores values that survive app restarts — counters, timestamps, API responses, user preferences." Also `cache/patterns.md:23`, `:66` ("structured app state"), and `apps/task-bucket.md:129` ("persisting data across restarts").
- **The design calls it disposable.** Spec 013 (`design/specs/013-resource-cache-redesign/design.md:243`) says loss on a format change is "acceptable for a cache — warm-up cost, not data loss."
- **The code treats it as disposable in three ways:**
  - Corruption at startup deletes and recreates the file (`src/hassette/cache/wrapper.py:93-128`).
  - An unpickle failure becomes a silent miss, and the row is deleted (`_helpers.py:81-95`, `wrapper.py:203-205`).
  - It has no schema version, and it leaves orphaned directories behind when a `cache_key` is renamed.
- **What it already does well.**
  - It is an independent WAL file with its own connection pair (`wrapper.py:135-145`).
  - `SyncCache` opens a fresh connection per call, so it is safe from `AppSync` worker threads (`cache/sync.py:1-9`).
  - SQLite serializes writers across instances and processes.
  - TTL, `get_or_set`, `invalidate`, a dummy, and harness backing already exist (`src/hassette/testing/app_harness.py:272-276`).
- **It isn't backed up safely.** Spec 129 D10's add-on backup handles only `hassette.db*` (`design/specs/129-ha-addon-v01/design.md:560-562`). WAL-mode `cache.db` files are tarred hot, and nothing found snapshots or excludes them.
- **Spec 155 D6 missed it.** The spec says "hassette has a database but no per-app key-value storage" (`design/specs/155-hacs-app-entities/design.md:190-191`).
- **No issue asks for a user-facing durable store.** Open cache issues are about correctness and testability: #2748 (split-brain when one sharer deletes a corrupt shared file), #3697 (DummyCache in the harness), #3972 and #3977.

## Peer comparison

| Peer | Classes distinguished | Owned-state format | Write strategy | Corrupt / too-new | App-facing API | Scope |
|---|---|---|---|---|---|---|
| **Home Assistant** | Recorder (telemetry) / `.storage` (owned config and registries) / `core.restore_state` (restore cache) / config entry `data` vs `options` (user overrides) | JSON envelope `{version, minor_version, key, data}` | `async_save` now, or `async_delay_save` debounced; one `asyncio.Lock` per store; temp file plus `os.replace`; fsync only for `atomic_writes=True` stores (registries, auth), whose helper warns that frequent use "will significantly negatively impact performance" (`util/file.py`) | Corrupt: renamed `.corrupt.<iso>`, start empty, persistent CRITICAL repair issue (`helpers/storage.py:426-475`). Newer major: `UnsupportedStorageVersionError`; for core registries, process-wide recovery mode with "on-disk data … preserved" (`bootstrap.py:513-531`, PR #164340). Any version mismatch re-saves the file stamped with the running code's version (`storage.py:479-513`) | `Store(hass, version, key, minor_version=…)` | Per integration key |
| **ESPHome** | Device: flash prefs vs RTC prefs. HA side: one Store per config entry as a device cache | Device: NVS blobs keyed by hash, size-checked, no version | Device: `flash_write_interval` 60 s for wear, flush on shutdown | Device: wrong size falls back to the initial value | `restore_value: yes`, `restore_mode:` | Per entity / per entry |
| **Node-RED** | Memory context vs file context, chosen per call | JSON per scope, `context/<flow>/<node>.json` | In memory, flushed every 30 s "to reduce wear", temp file plus rename, no fsync | "Invalid JSON in context file", no quarantine. No versioning | `flow.set(k, v, "file")` | Node / flow / global |
| **AppDaemon** | In-memory namespace vs persistent namespace (`safe` / `hybrid`) | `shelve` (dbm plus pickle per value), `<config>/namespaces/<ns>` | `safe`: `sync()` every write; `hybrid`: 1 s loop plus close | Refuses: any open failure raises `PersistentNamespaceFailed` (`appdaemon/state.py:185-213`). Persistence broke in 4.5.12-4.5.13 (#2533) | `set_state(..., namespace="storage")` | Global namespaces; per-app store asked for in #676 (2019), not built |
| **pyscript** | Restored `pyscript.*` entities only | HA `core.restore_state` | HA's 15 min plus stop; 7-day expiry | HA's | `state.persist("pyscript.x", default_value=…)` | Global by entity id; relies on HA internals ("this is a hack"), broke in HA 2022.3 (#331) |
| **NetDaemon** | v2: one JSON store. v3+: none | v2: `<id>_store.json` in `.storage` | v2: truncate and rewrite per save, no rename | v2: read errors swallowed, store treated as empty (`DataRepository.cs:41`) | v2: `SaveData(id, obj)` / `GetData<T>(id)` | Global id |
| **openHAB** | History persistence vs `restoreOnStartup` | Per service (MapDB latest value, rrd4j history) | Per strategy | — | `.persist` config per item | Per item |
| **Hubitat** | `state` (end of run) / `atomicState` (immediate) / `@Field` (lost on reboot) | JSON | End of execution vs immediate | — | `state.x = …` | Per app instance |
| **Homey** | App settings / device store / `/userdata` | JSON | Immediate | — | `this.homey.settings.set(k, v)` | Per app / per device |

**What the peers agree on (Supported, across HA, Node-RED, Hubitat, Homey and NetDaemon v2):**

- Owned app and integration state is scoped per app or integration.
- Telemetry and history live in a separate store with a disposable policy.
- Every peer that cares about wear or throughput batches writes, and none of them promises "committed before published".

**Where hassette would differ, and why:**

- **The app store is a KV database, not a JSON document.** The closest peer to an app-facing durable KV, AppDaemon's persistent namespace, is a dbm database with per-key writes. The JSON-document peers (Node-RED, Hubitat, Homey) have no worker-thread access to app state. hassette's `AppSync` does.
- **hassette copies HA's refusal on a newer version, not its minor versions.** HA re-stamps on mismatch, and that is only safe because HA writes additive fields so they can be re-derived (verified; see the versioning section).
- **hassette refuses the consumer where HA starts empty.** HA can start empty because it raises a persistent repair issue and, for core stores, stops normal operation. A per-instance refusal is hassette's version of both, with the corrupt file itself as the persistent marker (recovery section).
- **The frameworks that persisted crudely paid for it.** AppDaemon's shelve regressions, pyscript's breakage on HA internals and NetDaemon v2's truncate-in-place store all lost or blocked user data. hassette's version of that cost is today's delete-on-corrupt pickled cache.

## Verdict 1: ATTACH vs independent stores

**Independent stores.** This holds on a clean slate.

| | ATTACH (prior Option B) | Independent stores |
|---|---|---|
| **Fault coupling** | One connection pair. An unreadable `hassette.db`, a heartbeat strike-out (which fails and restarts `DatabaseService`, `database_service.py:543-631`) or a wedged writer takes owned writes down with it. | An owned store fails only for its own reasons. Telemetry can be moved aside without touching owned state. |
| **Latency coupling** | Owned writes queue behind telemetry on one FIFO writer (`database_write_queue.py:31-75`). A retention cycle is a single queued job looping up to 100 × 1000 rows per target (`database_retention.py:126, 204`; `config/models.py:134,138`). Supported: queue shape read directly; how long a real cycle takes was not measured. | Each file has its own connection pair. |
| **Cross-file atomicity** | Not crash-atomic in WAL (sqlite.org/lang_attach.html). It needs a "no job spans both" rule plus a test. | Impossible by construction. The authority rules below make that safe. |
| **Per-file settings** | `journal_mode` is all-or-one; `synchronous` and `query_only` are set per schema. | Each store owns its settings (`FULL` for owned, the existing setting for telemetry). |
| **UI composition** | One SQL join for #4219's listing. | Join in Python on `(app_key, instance_name)`. The data is small, and spec 157's core service keeps a committed in-memory copy. |

**Clean-slate vs current code.** The case for ATTACH rested on reusing `DatabaseService` and on spec 132's "the UI reads the DB". Neither is a merit argument. The current-code cost of going independent is a second read source for `TelemetryQueryService` (`core/telemetry/query_service.py:72-74`), and a loader so seeded `seed:serve` can serve owned data from a file without a running instance.

## Verdict 3b: the app-facing store

This decision comes first because the framework store's best format depends on it.

### Option A1 (recommended): harden `AsyncCache` in place

The store stays one SQLite file per resolved `cache_key`, with the same `cache_entries` table. It changes in five places:

- **Corrupt or too-new: refuse in place.** The file is left where it is, with no delete and no move. Every instance using it goes `FAILED` with a reason naming the file. This replaces `wrapper.py:93-128`, and it fixes #2748's split-brain at the source, because no instance ever unlinks a file its peers have open.
- **A schema version.** `PRAGMA user_version`: 0 is today's pickle format, 1 is JSON values.
- **JSON-native values instead of pickle.** The value is checked at `set()`, as in the codec section below. A row whose value won't parse raises a typed error from `get()` and is kept, not deleted (this replaces `_delete_stale` on decode failure, `wrapper.py:203-205`).
- **One store object per resolved path.** A process-wide registry makes this hold. It is #2748's suggested option (a), and it ends `busy_timeout` contention between sharers.
- **Housekeeping.** `synchronous=FULL` is set explicitly (today it isn't set, so it falls to the SQLite build default). Expired rows are purged when the file opens. The backup snapshot covers the file.

`get`, `set`, `get_or_set`, `invalidate`, `clear`, the TTL rules, the `.sync` facade and the harness backing are unchanged. Key listing and multi-key atomic updates become a `SELECT key` and a `BEGIN … COMMIT` if they ever earn API surface. They aren't needed for this model.

### Option A2: a new JSON-document app store (the draft's choice)

One JSON document per `cache_key`, with atomic rename, an in-memory copy and a serialized writer.

### Option A3: do less, and document the cache as disposable

The docs would say "best effort: may be wiped". That would tell the corpus's 24 durable-state uses to move elsewhere, with nowhere to go but hand-written files under `data_dir`.

| | A1: harden `AsyncCache` | A2: JSON document store |
|---|---|---|
| **Sync facade (`AppSync` threads)** | Unchanged: a connection per call | Redesign: worker threads must reach the loop-owned document and writer, and `guard_not_in_event_loop` is rebuilt |
| **Shared `cache_key` across instances (#2748)** | Registry plus refuse-in-place | A registry is required. Without it, two in-memory copies race and the last rename wins silently |
| **Two processes on one `data_dir`** | SQLite serializes writers | The loser's whole document is dropped silently; it would need `flock` |
| **Write cost** | Per row | Whole document per write, growing with stored size |
| **Expired TTL entries** | One `DELETE` at open | Carried in every rewrite until read |
| **Backup** | Needs the snapshot command | Consistent by rename, no snapshot |
| **Readable by the UI, seeds, a person** | Yes: JSON values in rows | Yes |
| **New code** | Edits to `src/hassette/cache/`, plus the registry and status reporting | A new module, a codec, a registry and a sync bridge |

**Verdict: A1.** It keeps everything the corpus relies on and fixes the three defects with local changes. A2's only real advantage is backups with no snapshot step, and the framework store's backups need the snapshot command anyway (3a). This holds on a clean slate: an app-facing durable KV with worker-thread access and sharing across instances is a database's job, and AppDaemon, the nearest peer, also uses a KV database. The cheapness of A1 comes from current code. The choice itself doesn't depend on it.

**Not "no new public API".** The draft's claim is withdrawn. Pickled values stop working: the accepted types narrow to JSON-native ones, there is a new typed error for an unreadable stored value, and there is a one-time reset of pickled entries. The `self.cache` → `self.store` rename is decided (2026-11-19).

## Verdict 3a: the framework owned-state store

The framework has two clients, entities (spec 157) and overrides (#3285). Entities are built on spec 157 as ratified (`027.sql`, an `integration_entities` table in `hassette.db`, PR #4284); overrides (#3285) haven't started. Entities move to `hassette-state.db` after #4284 merges, as a separate issue. All their SQL sits in `core/integration_store.py`, so the move swaps that module's backend.

### Option B1 (recommended): `hassette-state.db` on the hardened file layer

- **Tables.** One SQLite file in `data_dir` with two tables: `entities(app_key, instance_name, doc, pruned_at)` and `overrides(app_key, instance_name, doc)`. Each row holds one JSON document per instance. The entity document is spec 157 D4's per-entity records. The override document is the instance's raw `field → value` map.
- **Writer.** The file layer is shared with the app store. The write policy belongs to the client: spec 157's core service holds one lock across commit, then memory, then revision, and it shields a started write. That is D10 verbatim.
- **Commits.** D9's replace-the-set is one row upsert. A `set()` rewrites one instance's document, which is a few KB at most because it scales with that instance's declarations.

### Option B2: HA-`Store`-style JSON files

One JSON file per instance (or one file), atomic rename, fsync of the file and its directory. This is the framework half of the draft's Option 4.

### Option B3: a table in `hassette.db`

Spec 157 as ratified, the prior brief's Option 1. It fails on a clean slate. Every documented recovery path for `hassette.db` (corruption, too-new schema, rollback, "safe to delete") would reset switches, sensors and overrides. With 26 migrations in about five months, those paths aren't rare.

| | B1: `hassette-state.db` | B2: JSON files |
|---|---|---|
| **D9 replace-the-set atomic** | One upsert | One rename |
| **D10 written as is** | Yes; the lock lives in the core service | Yes; same |
| **fsyncs per commit** | 1 (WAL, `FULL`) | 2 (the file, then the directory after rename), plus `EINVAL` handling on some filesystems |
| **Backup** | Rides the snapshot command the app stores need anyway | Consistent by rename |
| **Corruption blast radius** | Every instance with entities (one file) | One instance (one file each) |
| **Rollback** | Integer version, newer refuses. Same as B2 under the versioning section | Same |
| **Code** | Reuses the hardened file layer | A new file helper (atomic write, fsync of file and directory, temp-file sweep, envelope) |
| **Two processes, reads during a write** | SQLite handles them | Needs a lock or an accepted limitation |
| **Hand-editing** | `sqlite3` CLI | A text editor, only with hassette stopped, since a running hassette rewrites the file from memory. HA's docs say the same for `.storage` |
| **Storage technologies in hassette** | One (SQLite) | Two |

**Verdict: B1, with B2 a close second.** Given decision 3b, JSON's backup advantage is gone. Its rollback advantage depended on minor versions, which aren't write-safe. Hand-editing needs hassette stopped. "HA convention" concerns an internal format here. What B2 keeps is a per-instance blast radius and one less snapshot path. B1 wins on one technology, shared code and one fsync per commit.

This holds on a clean slate only *given* that the app store is SQLite. With no app store at all, B1 vs B2 would be close to a coin flip on these criteria. **Pick B2 instead if** the add-on snapshot for owned SQLite files is rejected, or the app store moves off SQLite.

### What is shared between 3a and 3b, and what isn't

| Shared: the file layer (in or beside `src/hassette/cache/`) | Not shared: each client's own |
|---|---|
| Opening with WAL, `synchronous=FULL` and `busy_timeout`; the integrity check; corruption detection (`_CORRUPTION_INDICATORS`) | Tables and document shape |
| The `user_version` gate and refuse-in-place, reported to one store-status registry | The write policy: D10's lock, shield and publish for entities; plain awaited writes for the app store |
| The process-wide one-object-per-path registry | TTL and expired-row purge (app store) |
| JSON-native encode, plus the strict check and decode with a typed error | Tombstones (entities); validation against the config model (overrides) |
| Listing owned files for the snapshot command and the orphan check | The `.sync` facade (app store). `self.integration.sync` goes through spec 157's loop writer |

## Recovery policy, per store

The deciding factor is that no consumer acts on a false "no state" without a human having decided it should.

| | Entities (`hassette-state.db`) | Overrides (`hassette-state.db`) | App store (`cache.db`) | `hassette.db` (observed) |
|---|---|---|---|---|
| **Whole file corrupt** (won't open, or fails `integrity_check`) | File left in place. Every instance that declares entities goes `FAILED` with a reason; instances without entities run | File left in place. Overrides unavailable, file config applies | File left in place. Every instance sharing that `cache_key` goes `FAILED` | Moved aside, fresh file, WARNING |
| **One unreadable value** | One instance's document won't parse: that instance goes `FAILED` and the row is kept. A value that fails the new declaration's D5 check: spec 157 D12 (becomes `unknown`, WARNING) | One instance's map won't parse: that instance's overrides are skipped and kept, CRITICAL. One field fails validation: skipped, kept, reported as a stale override | `get()` raises `StoredValueError` (a `HassetteError`) naming the key; the row is kept | n/a |
| **Too-new version** | As corrupt; the file is untouched | As corrupt | As corrupt | Moved aside, fresh file |
| **Writes while unavailable** | None: the consumers aren't running. A leaked handle raises `IntegrationHandleClosedError` (spec 157) | Override writes raise a typed error; the web API returns it as a conflict | None: the consumers aren't running. A leaked call raises | n/a |
| **Signal** | `FAILED` reason, CRITICAL on `/health` and the UI banner | CRITICAL on `/health` and the UI banner | `FAILED` reason, CRITICAL | WARNING plus a health note |
| **Human resolves by** | Restoring the snapshot, or deleting the file to accept a reset | Same | Same | Nothing needed |

**Why refuse instead of starting empty (entities, app store).**

- **Apps act on absence with side effects.** The corpus shows it: `meeting_app.py:141` snapshots lights that may hold meeting colors, and `car_climate.py:374,613` can double-start the car. Those apps don't check status flags, and a status API would be one more thing every app must learn.
- **Entities would overwrite HA.** Starting empty republishes switches at `initial`, which overwrites the user's last commanded state in HA.
- **Refusing is what the peers do when they stop.** AppDaemon refuses (`PersistentNamespaceFailed`). HA starts empty only alongside a persistent repair issue, and on a newer core store it stops normal operation.
- **Leaving the file in place keeps the signal and fixes #2748.** The bad file itself is the persistent marker, so the signal survives restarts with no new state until a human restores or deletes it. And no recovery code ever unlinks a file that peers have open.

**The cost is availability.** An affected app doesn't run until someone acts. The blast radius is one `cache_key` for app stores, and every entity-declaring instance for the framework file. **Pick start-empty instead if** you'd rather apps keep running after a recovery and accept a store status every app author must check (needs-user, below).

**Why overrides differ.** When the overrides map can't be read, hassette can't tell which instances it covered, so it can't refuse per instance. Its fallback is the user's own file config, a known-good configuration the user wrote, not "nothing". That justifies #3285's "never blocks startup" on merit, and makes the conflict with refusing disappear. Refusing override writes (rather than moving the file aside and starting a fresh one) means a later restore never collides with overrides written in the meantime. #3285's "a missing or corrupt store reads as empty with a logged error" becomes "is unavailable: file config applies, writes raise, CRITICAL health". A missing store is a first run and reads as empty.

**First run vs reset.** Under this policy an app never sees a reset that a human didn't choose. The only resets are a human deleting the file, and the one-time pickle-to-JSON reset at the upgrade that changes the format, which the release notes name. So no `was_reset` API is needed. That API only becomes necessary under the start-empty alternative.

**The health signal is part of issue 1, not a follow-up:**

- Every owned store reports `ok`, `refused(corrupt)`, `refused(too_new: found, supported)`, `unavailable` (overrides) or `orphaned` to one store-status registry in core.
- The registry feeds `/health` (degraded, listing stores and files), the UI banner (spec 132 D23), and each affected instance's `FAILED` reason. The `hassette status` CLI shows the same reasons.
- The registry is rebuilt from disk at each start, so the signal lasts until the file is fixed.
- An HA repair issue through hass-hassette, HA's own analog, can follow, because it reads `/health`.

## Versioning

**A single integer version per owned file (`PRAGMA user_version`).** A file newer than the code is never written: its consumers refuse, or for overrides it is unavailable. An older file is migrated forward on open.

**Why not HA's major/minor scheme.** Verified in HA's source: on *any* version mismatch where the major matches, `_async_migrate_func` raises `NotImplementedError` for a minor-only difference. The data then passes through raw, and `async_save(stored)` re-stamps the file with the running code's minor version (`helpers/storage.py:479-513`). HA's registries then load into typed `attr` classes and save only the fields they know. So old code that reads a newer minor drops the newer fields on its next save, and when you upgrade again the file claims the old minor. HA lives with this because it writes additive fields to be re-derivable. The entity registry's 1.22 migration says "To avoid a major version bump, we keep the old aliases as-is and use aliases_v2 field instead", and re-running that migration after a rollback rebuilds `aliases_v2` from `aliases` (`helpers/entity_registry.py`, peer copy lines 1038-1047). Copying HA's minor versions safely would mean `extra="allow"` on every record model plus a never-lower-the-stamp rule. That is machinery with no current consumer.

**Keep the versioned part narrow, so bumps stay rare.** This applies the same idea as HA's: what can be re-derived isn't versioned owned data.

- **Entity declarations are re-derived from app code at every running-time commit** (D9 replace-the-set). They are read leniently, ignoring unknown fields, and adding a declaration field is not a version bump. Old code saving a document drops the new field, and new code re-derives it at its next commit.
- **Values and attributes are opaque JSON** (spec 157 already stores them as JSON).
- **Overrides are a raw `field → value` map**, validated against the config model when applied. Unknown fields round-trip by construction.
- **The app store's version covers only hassette's table shape.** Apps version their own values, as the corpus already does (`RECORD_VERSION`).

The bump rule for `.claude/rules/` is: bump only when old code would misread or lose owned data.

**Cost.** A rollback across a real bump stops entity-declaring instances, or the instances sharing an app store, until the user upgrades or restores. `hassette.db`'s 26 migrations in about five months are churn in observed tables. The owned part is deliberately narrow so the same churn doesn't reach it (Inferred: no owned schema has a history yet). This holds on a clean slate, and it matches the pre-v1 preference for the smallest scheme.

**Ordering for the pickle-to-JSON change.** Today's `cache.db` has no version gate, so pre-gate code reading JSON rows would fail to unpickle them and delete them (`_delete_stale`). Ship the gate (issue 1) in a release before the format change (issue 3). A rollback from the format release to the gate release then refuses safely. A rollback past the gate release is an accepted limitation, and the release notes say to restore the snapshot.

## Value codec for the app store

**Rule (a gate for issue 3):** a stored value must be JSON-native: `None`, `bool`, `int`, a finite `float`, `str`, `list`, or a `dict` with `str` keys, nested to any depth. `set()` raises `TypeError` naming the offending path for anything else. That includes tuples and non-`str` keys, which `json.dumps` would otherwise convert silently. `get()` returns exactly what was stored.

hassette adds no typed read. An app that wants a model back converts it itself, with its own model or pydantic's `TypeAdapter`. `whenever` 0.11 types carry a pydantic schema (`whenever/_common.py:451`), so the conversion is one line. A typed `get(key, type=...)` could be added later if call sites show the boilerplate.

| Corpus value today | What a permissive JSON codec would do | Under the rule |
|---|---|---|
| `dict[str, LightSnapshot]`, a frozen dataclass with a `tuple` field (`meeting_app.py:28-35`, set at `:139, 189, 489`) | Returns dicts; `prior_snap.was_on` raises `AttributeError` at `:460`, far from the cause | `TypeError` at `set()`; the app stores `asdict()` and rebuilds |
| `set[Person]` (`garage_proximity/app.py:64`) | Returns a list; `isinstance(…, set)` at `:59` fails, so the app silently treats every restart as "nobody was home" | `TypeError` at `set()`; the app stores a sorted list |
| `ZonedDateTime` (`monarch/updater.py:383`) | Returns a str; the `assert isinstance(…, ZonedDateTime)` at `:366` fails on every start | `TypeError` at `set()`; the app stores `format_iso()`, as more than ten other corpus call sites already do |
| `list[tuple[float, float]]` (`thermoscura.py:612`) | Returns lists of lists; the unpacking at `:566` still works | `TypeError` (tuple); the app stores lists |
| Versioned plain dicts, ISO strings, scalars (`bedtime_state.py`, `announcer.py`, `travel_status/app.py`, `desk_stand_nudge.py`, and most others) | Round-trips | Unchanged |

**Why not keep pickle.** Pickle gives exact round trips, means no app changes, and needs no reset. But it ties stored data to class paths: renaming or moving a class makes the stored value unreadable. That is the failure the corpus author hardened three apps against, with comments saying so. It also can't tell a renamed class from bit rot, and the monitoring UI, seeds and a person recovering by hand can't read the values. **Why not a permissive codec:** the second row of the table is a silent behavior change that no error would ever surface. JSON-native-only matches HA `Store` and Node-RED. NetDaemon v2's typed `GetData<T>` is the alternative, and it remains available later as an addition. This holds on a clean slate.

## Deletion

**Rule:** recovery code never deletes owned data. Owned data is deleted only by an explicit, logged, owner-scoped operation:

- **App store.** The app's own `delete`, `clear` or TTL, and the user deleting a file. The one-time format reset at the pickle-to-JSON upgrade is an explicit, release-noted migration.
- **Entity key removed by the app's code** (spec 155 D6, spec 157 D9). Hard delete, as ratified, because a re-declared key must start fresh and the app author's code is the authority.
- **Instance absent from config at startup** (the spec 155 D13 / spec 157 prune). This becomes a **soft delete**. The instance's row gets `pruned_at` and is kept for 30 days. If the same `(app_key, instance_name)` returns to config within the window, its document is restored. Rows older than the window are purged at startup and logged.
  - **Why:** parent spec 155 D13's own deciding factor is cleaning up "without risking data loss from a config edit or typo", and spec 157 accepted that a wrong apps config "prunes every instance's declarations and switch and sensor state". A tombstone makes the typo recoverable by fixing the config and restarting.
  - **Peer:** HA's entity registry keeps a removed entity in `deleted_entities`. Once its config entry is gone, the entry is purged after `ORPHANED_ENTITY_KEEP_SECONDS` = 30 days, and a re-added entity gets its settings back (`helpers/entity_registry.py`, peer copy lines 97, 1826-1859, 2750-2763). HA's tombstone keeps registry settings, not state values, so carrying the value is hassette's own extension.
  - **Cost:** a `pruned_at` column, a restore on commit, and a purge step. It amends spec 157's prune bullet.
- **Orphaned app-store files.** A `cache.db` under `data_dir` that matches no resolved `cache_key` in the loaded config (`config/config.py:627`, `resolve_cache_keys`) is reported as `orphaned` in health and never deleted. A `cache_key` rename otherwise leaves the old state behind silently, and the new key starts empty. That is a user action, so this policy permits it.

All of this holds on a clean slate.

## Write path

**No group commit.** Each changing `set()` is one commit: an upsert in autocommit mode with `synchronous=FULL`, so one WAL fsync. Spec 157 D13 already makes an identical `set()` a no-op. With per-instance documents in one file, entity writes from all instances serialize on one connection, and each costs one small document upsert.

Spec 157 D10 applies verbatim, with the writer living in the core service instead of `DatabaseService.submit()`. One lock spans commit, memory and revision. A started write is shielded and completes. A not-started write is withdrawn. A failed write raises to its caller and leaves memory at the last commit. Nothing about batches needs specifying, because there are none.

**Why drop it.** Group commit existed to make whole-file JSON rewrites affordable. Per-row SQLite commits don't need it. No peer coalesces under a committed-before-published promise, and coalescing would have rewritten D10's failure and cancellation semantics. If the prototype shows per-commit latency hurting at realistic rates, the lever is the sensor promise (restore-class sensors, switches unchanged), which leaves D10 intact.

## Cross-store rules and accepted limitations

**Authority rules (closing the cross-store open question):**

- The loaded apps config is authoritative for whether an instance exists.
- Owned stores are authoritative for values.
- Owned stores never hold `hassette.db` ids, which change when the observed file is regenerated.
- The listing joins on `(app_key, instance_name)`. An instance with owned data but no observed rows (after a `hassette.db` reset) is shown from config and owned data. Observed rows with no owned document show no entities.
- No write must be atomic across files. The one pair found, an override (owned) and the per-session effective-config projection (observed), heals at the next app creation, because the projection is rebuilt from the owned side (Inferred from #2768's design; worth confirming when #3285 is sketched).

**Accepted limitations:**

1. **Backups are consistent per file, not across files.** A restore can pair `hassette-state.db` and `hassette.db` from slightly different moments. The authority rules make the join well defined.
2. **The app store has no size bound** (challenge Finding 20). Writes are per row, so cost doesn't grow with size, and expired rows are purged at open. Large or high-churn data belongs in app-owned files under `data_dir`, and the docs say so.
3. **`data_dir` must be on a local filesystem** (challenge Finding 21, in SQLite form). SQLite's locking and fsync are unreliable over NFS, SMB and some FUSE or 9p mounts (sqlite.org/useovernet.html, sqlite.org/howtocorrupt.html §2). This already holds for `hassette.db`. The snapshot command must use SQLite's backup API or `VACUUM INTO`, never raw file copies.
4. **One hassette process per `data_dir`.** SQLite keeps a second process from corrupting files, but the per-path registry and the refusal policy assume one owner.
5. **Rolling back past the release that adds the `cache.db` version gate** loses JSON-format app values, as described in the versioning section.

## Options evaluated (summary)

| Option | What it is | Clean-slate verdict | Current-code cost |
|---|---|---|---|
| **1. Do less** | Spec 157 as ratified (table in `hassette.db`), plus cache docs saying "best effort" | No. Every `hassette.db` recovery path resets desired state, and the docs would tell users their durable store isn't durable | Trivial |
| **2. ATTACH** (prior brief's B) | `hassette-state.db` attached to `DatabaseService`; cache untouched | No (verdict 1) | Medium |
| **3. JSON `Store` primitive for both** (this brief's first draft) | New JSON module; framework stores and `self.cache` rebuilt on it, with group commit and major/minor versions | No. Every point in the revision table, chiefly a redesigned sync facade and the app store's shared-key and cross-process gaps, and a minor-version rollback that isn't write-safe | Large |
| **4. Harden the SQLite KV; framework state in `hassette-state.db` on the same file layer** (recommended) | Decisions 3a (B1) and 3b (A1) | Yes for the app store. Yes for the framework store given the app store, with B2 (JSON) close | Medium |
| **4′. As 4, but framework state in JSON files** | 3a = B2 | Close second. Pick it if owned SQLite backups are rejected | Medium |

## Concerns

### Technical risks

- **Per-commit fsync latency on SD-card storage** is unmeasured. A wedged write holds an instance in `STARTING` (157 D10.5), unchanged.
- **The refusal policy trades availability for correctness.** One corrupt framework file stops every entity-declaring instance, and one corrupt shared `cache.db` stops all its sharers. With SQLite `FULL` and atomic commits, whole-file corruption should mostly mean hardware or filesystem faults (Inferred). A rollback across a version bump is the likelier trigger.
- **The pickle-era rollback hole** described in the versioning section.
- **Spec 132's "no route reads process memory".** Live owned-state routes read the core service's committed memory, and snapshot mode reads `hassette-state.db`. Spec 132 D11 already carves out config, so this is an amendment (Inferred from the ledger text).

### Complexity risks

- **A store-status registry is a new cross-cutting piece.** It is also what keeps the refusal and fallback paths from going dark, so it is not optional.
- **The tombstone adds a restore path to spec 157's commit.** It needs one test: prune, fix config, restart, value back.

### Maintenance risks

- **The version-bump rule** ("bump only when old code would misread or lose owned data") has to be applied on every owned-schema change. Put it in `.claude/rules/` beside the migration rules.
- **The JSON-native contract becomes a compatibility surface for user data.** It is narrower and more stable than pickle, which tied stored data to class paths.

## What changes elsewhere

- **The prior brief** (`design/research/2026-11-19-durable-state-vs-telemetry/research.md`):
  - **Superseded:** its recommendation (Option B, ATTACH) and its "Where spec 155's tables live" paragraph.
  - **Kept:** table classification, file-deletion paths, the telemetry move-aside follow-up (its #4), the classification test from its Option A, and the WAL/ATTACH facts.
  - **Changed:** its follow-ups 1-3 (state file, snapshot, add-on) become `hassette-state.db` plus one snapshot command covering every SQLite file. Its follow-up 5 (cache tearing in add-on backups) is resolved by that command.
  - **Correction:** its AppDaemon and pyscript peer row.
- **Spec 132** (ratified): amend inline plus a dated Addendum.
  - **Summary:** observed data (`hassette.db`, regenerable) vs owned data (`hassette-state.db` and app stores, never deleted by recovery code).
  - **D11:** override storage moves to `hassette-state.db`. The per-session effective config stays a projection in `hassette.db`.
  - **D4/D15/D16:** seeds write `hassette-state.db` when a scenario declares entities or overrides, and `seed:serve` opens it read-only.
  - **D20:** the required-DB contract covers `hassette.db`; owned stores follow the recovery table.
  - **D23:** the banner shows store statuses.
- **Spec 155** (ratified):
  - D6's "entity-state table in hassette's DB" becomes "`hassette-state.db`". Correct "no per-app key-value storage".
  - D13's startup prune becomes a 30-day tombstone.
  - D6's committed-before-published promise is kept.
- **Spec 157** (ratified; built as PR #4284 with `027.sql` in `hassette.db`). It stays as the record of what shipped; the move below happens in a follow-up issue, which records itself in a spec 157 Addendum:
  - **Persistence:** the `integration_entities` table moves out of `hassette.db`. A per-instance JSON document in `hassette-state.db`, keeping D4's per-entity record fields.
  - **D4:** ratified a table with typed columns, "accepting a migration per new declaration field". It becomes a document, so adding a declaration field needs no migration and no version bump. "Removed declaration, removed state" is still one write, now one document.
  - **D10:** verbatim, with the lock in the core service instead of `DatabaseService.submit()`.
  - **Startup prune:** becomes the tombstone.
  - **Harness:** the in-memory store is unchanged.
  - **Assumed:** the hardened file layer exists.
- **Spec 129 D10:** an Addendum. `backup_pre` calls a hassette snapshot command that copies `hassette-state.db` and every `cache.db` (`hassette.db` is excluded by default, decided 2026-11-19) with the SQLite backup API. The live files are excluded and the restore step covers each file. Whether `backup_exclude` globs can match nested `cache.db` files is Assumed in spec 129 and needs checking (open question).
- **Spec 013:** "acceptable for a cache" is superseded.
- **#2695:** "required" means `hassette.db`; owned stores follow the recovery table. Drop the `cache_entries` claim. The docs rewrite names both kinds of storage.
- **#2748:** fixed by the per-path registry plus refuse-in-place (issue 1).
- **#2768 / #3285:** storage moves to `hassette-state.db`, and #3285's title ("Add a DB-backed store…") changes. The corrupt-store criterion becomes "unavailable: file config applies, writes raise, CRITICAL health, file never deleted". Add "a field that fails validation is kept and reported as stale".
- **#3697:** the harness keeps tmp-dir `cache.db` backing and gains seed and read accessors (issue 3).
- **#4218 / PR #4284:** ships as built (entity table in `hassette.db`, docs already say a delete resets declared switches and sensors). The move to `hassette-state.db` is a follow-up issue after issue 1.
- **#4277:** answered by this brief plus the prior one.
- **Cache docs:** `docs/pages/core-concepts/cache/*`, `troubleshooting.md` ("Cache Not Persisting") and `operating/upgrading.md` state the durable promise, the JSON-native rule, the refusal behavior and how to resolve it, the one-time reset, and the rollback caveat.

## Proposed follow-up issues

Filed 2026-11-19 in the *Owned State Durability* milestone: 1 → #4294, 2 → #4295, 3 → #4296, 4 → #4297, 5 → #4298, 6 → #4299.

1. **Harden the SQLite KV file layer as hassette's owned-state store.** Covers:
   - Refuse-in-place on corrupt or too-new files, with a `user_version` gate.
   - `synchronous=FULL` and a purge of expired rows at open.
   - A process-wide store object per path (fixes #2748).
   - The store-status registry, surfaced in `/health`, the UI banner, `FAILED` reasons and the CLI, plus the orphan check.

   Must ship a release before issue 3. Blocks #3285, issue 2 and issue 3.
2. **Move app-declared entity state from `hassette.db` to `hassette-state.db`.** Swap `core/integration_store.py`'s backend, drop `integration_entities` from `hassette.db`, add the 30-day tombstone (spec 155 D13 amendment), and decide copy-once vs reset-once for existing values. Record the change in a spec 157 Addendum. After issue 1 and #4284.
3. **Switch app-store values from pickle to JSON-native.** Covers:
   - The strict check at `set()` and `StoredValueError` on an unreadable row, with the row kept.
   - The one-time reset of format version 0 files.
   - Harness seed and read accessors (settles #3697).
   - Docs, the breaking-change note, and the `self.cache` → `self.store` rename.
4. **Add a snapshot command covering every hassette SQLite file**, and have the hassette-addon `backup_pre` and restore glue call it (an add-on issue in hassette-addon, after this lands).
5. **Move a corrupt or newer-schema `hassette.db` aside instead of stopping.** Carried over from the prior brief, unchanged.
6. **Classify every `hassette.db` table and pin it with a test.** From the prior brief's Option A.

`hassette-state.db` itself ships inside issue 2 (entities) or #3285 (overrides), whichever lands first, so it gets no separate issue. Comment on #2695 (scope, `cache_entries`) and #3285 (retitle, revised criteria) rather than filing new issues.

## Open questions

- [x] **needs-user (decided 2026-11-19: refuse the instance):** Refuse the consumer (recommended) or start empty with a store status apps must check, for entity and app stores after a corrupt or too-new file? This is availability vs never acting on false state. The rest of the recovery design holds either way, but start-empty adds a public `was_reset`-style API.
- [x] **needs-user (decided 2026-11-19: rename to `self.store`):** Rename `self.cache` to `self.store`? The name "cache" is what let specs 013 and 155 treat it as disposable. Pre-v1 allows the rename.
- [ ] **needs-user, conditional on the prototype (2026-11-19: deferred until the latency numbers exist):** If per-commit latency hurts, relax sensor values to restore-class (a debounced write that can lose the last seconds on a crash), keeping switches committed-before-published?
- [x] **needs-user (decided 2026-11-19: exclude by default):** Should add-on backups exclude `hassette.db` by default now that it is purely observed, as HA offers with `exclude_database`?
- [ ] **needs-prototype:** Per-commit latency (p50/p99) on SD-card-class storage with `synchronous=FULL`: entity sensors changing at 1 Hz across 10 instances on one `hassette-state.db`, concurrently with app-store writes to several `cache.db` files. This decides whether the sensor question above is needed. It no longer decides the format.
- [ ] **needs-investigation:** Whether Supervisor's `backup_exclude` patterns match nested paths (`*/cache/cache.db*`). Spec 129 marks the pattern semantics as Assumed, and the snapshot command's exclude list depends on the answer.
- [ ] **Unknown, searched:** why NetDaemon v3 dropped `SaveData`/`GetData`. Searched NetDaemon issues, discussions, release notes and the v3 PR, and found no stated reason.

## Recommendation

**Take Option 4 (A1 plus B1), staged:**

1. **The file-layer hardening and status registry (issue 1).** It fixes #2748 and stops deleting user data on its own, so it is worth shipping even if nothing else lands.
2. **Entities move to `hassette-state.db` (issue 2), and #3285 builds on it.** #4284 ships first with entities in `hassette.db`.
3. **The pickle-to-JSON value change (issue 3)**, at least one release after issue 1.
4. **The snapshot command and add-on glue.**

**How strong each part of the evidence is:**

- **Direct:**
  - The corpus's durable use of the cache and its pickle-dependent call sites (quoted).
  - The docs' promise against the code's delete-on-corrupt.
  - HA's re-stamp on a version mismatch, its recovery mode and its 30-day orphan retention (source read).
  - AppDaemon's refusal (source read).
- **Supported:** the ATTACH coupling costs (queue and retention code read). That the SQLite KV meets the app store's concurrency needs, which a JSON document would have to rebuild (`sync.py`, `app.py:188-192`, and #2748's text).
- **Inferred:**
  - That per-commit `FULL` latency is acceptable at realistic rates (the prototype checks this).
  - That whole-file corruption is rare enough for the refusal policy's availability cost.
  - That the owned schema will rarely need a version bump.

**What holds without the current code:** the observed/owned split, independent files, a SQLite KV for the app store, the per-consumer recovery policy, integer versions over a narrow owned schema, JSON-native values, recovery code that never deletes, and per-commit writes without batching. **What exists because of current code:** that the hardening is cheap (the cache already exists), and the amendment list.

### Suggested next steps

1. Decide the first two needs-user questions (refusal policy, naming), then sketch issue 1 via `/mine-sketch`. It adds a cross-cutting status registry and changes failure behavior users see.
2. Run the latency prototype against a `hassette-state.db` and several `cache.db` files on SD-class storage. That settles the sensor question.
3. Amend specs 157, 155, 132 and 129, then file issues 1 and 3 and comment on #2695 and #3285.

## Sources

**hassette (this worktree):**
- `design/research/2026-11-19-durable-state-vs-telemetry/research.md`
- `src/hassette/cache/wrapper.py` (93-145, 160-205), `_helpers.py` (64-95), `protocol.py` (25-40), `sync.py` (1-60), `dummy.py` (28-40)
- `src/hassette/app/app.py:186-192, 281-290`; `src/hassette/config/config.py:616-666`
- `src/hassette/utils/aiosqlite_utils.py:44, 189`
- `src/hassette/core/database_service.py:543-631`, `database_write_queue.py:31-75`, `database_retention.py:126, 204`, `config/models.py:134, 138`, `core/telemetry/query_service.py:72-74`
- `src/hassette/web/auth/tokens.py:151-170`; `src/hassette/migrations_sql/` (26 files)
- `docs/pages/core-concepts/cache/index.md:3`, `cache/patterns.md:23, 66`, `docs/pages/core-concepts/configuration/index.md:118`
- Specs: `013-resource-cache-redesign/design.md:243`; `155-hacs-app-entities/design.md` (D6, D13); spec 157 (branch `4218`; scratchpad copy `/tmp/claude-1000/-home-jessica-source-hassette/540d8a14-cd6e-49df-b342-913c853caf0d/scratchpad/mine-research-olbnor/spec157.md`: Summary, D4, D5, D10, D12, D13); `132-db-source-of-truth/design.md` (D1, D11, D20, D23); `129-ha-addon-v01/design.md:536-566`
- GitHub issues (NodeJSmith/hassette): #2695, #2748, #2768, #3285, #3697, #3993, #4218, #4277, #1753
- Challenge results: `/tmp/claude-1000/-home-jessica-source-hassette/540d8a14-cd6e-49df-b342-913c853caf0d/scratchpad/mine-challenge-ZlwO3R/challenge-results.md` and the three critic reports beside it

**Real-user corpus:** `~/source/hautomate/`
- `src/hautomate/`: `meeting_app.py`, `garage_proximity/app.py`, `garage_proximity/constants.py`, `monarch/updater.py`, `thermoscura.py`, `dryer_humidity.py`, `bedtime_state.py`, `announcer.py`, `travel_status/app.py`, `desk_stand_nudge.py`, `porch_lights.py`, `car_climate.py`, `notify.py`, `trackers.py`
- `config/hassette.toml`; `design/specs/004-bedtime-state-and-steps/design.md`; `design/audits/2026-11-01-consolidation/synthesis.md`; commits `cdaaaa8`, `c21d9ea`

**Home Assistant** (peer copies in `peersA-JxUfMA/`):
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/storage.py (corrupt path 426-475; version handling 479-513)
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/entity_registry.py (`ORPHANED_ENTITY_KEEP_SECONDS`, `deleted_entities`, minor migrations including `aliases_v2`)
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/restore_state.py
- https://github.com/home-assistant/core/blob/dev/homeassistant/util/file.py
- https://github.com/home-assistant/core/blob/dev/homeassistant/bootstrap.py (492-531)
- https://github.com/home-assistant/core/blob/dev/homeassistant/exceptions.py
- https://github.com/home-assistant/core/pull/164340
- https://developers.home-assistant.io/docs/config_entries_options_flow_handler/

**ESPHome:** https://esphome.io/components/preferences/; HA `components/esphome/entry_data.py`

**Node-RED:** https://nodered.org/docs/user-guide/context; `@node-red/runtime/lib/nodes/context/localfilesystem.js`

**AppDaemon:** https://github.com/AppDaemon/appdaemon (`appdaemon/state.py:185-217`, `appdaemon/exceptions.py:257`); issues #2533, #676

**pyscript:** https://github.com/custom-components/pyscript (`state.py`); issue #331

**NetDaemon:** https://github.com/net-daemon/netdaemon_v2 (`DataRepository.cs`); https://github.com/net-daemon/netdaemon; discussion #1394

**Others:** https://www.openhab.org/docs/configuration/persistence.html; https://docs2.hubitat.com/en/developer/app/overview; https://apps.developer.homey.app/the-basics/app/persistent-storage; https://github.com/wibias/hass-variables

**SQLite:** https://www.sqlite.org/lang_attach.html; https://www.sqlite.org/pragma.html; https://sqlite.org/useovernet.html; https://sqlite.org/howtocorrupt.html

**whenever:** installed 0.11.0, `whenever/_common.py:451` (`__get_pydantic_core_schema__`)

**Search tooling.** Web research used `exa-search` throughout, with no WebSearch fallback. Peer source was cloned shallow into the scratchpad (`peersA-JxUfMA/`, `peersB-kvohlQ/`).

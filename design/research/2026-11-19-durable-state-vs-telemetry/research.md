# Research Brief: Keep durable runtime state separate from regenerable telemetry

```yaml
proposal: "Decide whether hassette should keep durable runtime state (app-declared entity state and declarations, config overrides) in a store separate from the regenerable telemetry in hassette.db, as Home Assistant, ESPHome and Node-RED do, and where spec 155's entity tables live."
date: 2026-11-19
status: Superseded
flexibility: Exploring
motivation: "Users are told hassette.db is safe to delete (docs/pages/troubleshooting.md:186). Spec 155/157 add the first state that exists nowhere else; the promise needs a clear, true answer."
constraints: "Personal-tool-ish framework, solo developer, pre-v1 (clean breaks, no compat shims), small installs (two-app new user is the common case). Must recommend where spec 155's durable tables live. No enterprise patterns."
non-goals: "Changing retention priorities; the cache API; HA-side (hass-hassette) behavior."
depth: deep
```

> **Superseded 2026-11-19 by [`../2026-11-19-persistence-model/research.md`](../2026-11-19-persistence-model/research.md).** Its recommendation (Option B, ATTACH) and the spec 155 placement are replaced by independent stores: `hassette-state.db` plus the hardened app store. Still standing: the table classification, the file-deletion paths, the telemetry move-aside follow-up, the classification test, and the WAL/ATTACH facts. Its AppDaemon/pyscript peer row is wrong; see the newer brief.

**Initiated by**: issue #4277, "Research keeping durable runtime state separate from regenerable telemetry storage".

## Bottom line

**Split, and do it before #4218's table ships.** Put durable state in a second SQLite file beside `hassette.db` (working name `hassette-state.db`), attached to `DatabaseService`'s existing connections as schema `state`, with its own migration chain. `hassette.db` stays pure telemetry, so the "Safe to delete" promise stays true instead of being reworded. Spec 155/157's entity table and #2768's config overrides go in the state file. One rule makes the split safe: **no write job touches both files**, because SQLite does not make a commit spanning two attached WAL databases atomic across a crash.

The case for splitting rests on deletion and rollback, not on retention:

- **Every recovery path hassette documents ends in "delete `hassette.db`".** That covers a too-new schema, corruption, rolling back past a migration, and degraded mode. The schema changes often: 26 migrations between 2026-05-30 and 2026-11-15, 14 of them since 2026-10-02. Every rollback across one hits `SchemaVersionError`, and the documented fix is deleting the file. With durable rows in the same file, each of those paths quietly resets switches and sensor values (#4218) and, later, the user's config overrides (#2768).
- **A separate file lets telemetry get Home Assistant's recorder policy later.** On corruption or a too-new schema, hassette can move the file aside and start fresh instead of halting. Durable state keeps a strict policy: refuse, never auto-delete.
- **Durable writes can be made power-loss durable without slowing telemetry.** `synchronous` is set per schema, so the state file can run `FULL` while the telemetry file keeps `NORMAL`.

**What the split does not do.** It doesn't simplify log retention or the size failsafe (#1753). The failsafe already deletes only from an allow-list (`_FAILSAFE_TABLES`), and the log-wiping incident was fixed by exempting `log_records` (#2350). #1753's remaining scope, making failsafe activity visible, is unchanged.

**Cost:** medium. Most of it is a second migration chain, attaching one file, and snapshot and backup handling for a second file (including the add-on glue in `hassette-addon`). The prepared-for-later option, moving a bad telemetry file aside, is a separate follow-up.

## Context

### What prompted this

`docs/pages/troubleshooting.md:186` says: "**Safe to delete.** Deleting `hassette.db` only removes telemetry history. Your automations continue to run." `docs/pages/core-concepts/database-telemetry.md:203` repeats it for corruption. Spec 157 (#4218's ratified pickup ledger, on local branch `4218`, commit `a5df8452`, not yet on `main`) adds `migrations_sql/027.sql`, a table holding "the only copy of switch and sensor state". Its sketch challenge raised exactly this conflict: "The new table lands in a database the docs call safe to delete". The ratified answer was to reword the docs: deleting `hassette.db` "also resets declared switch and sensor values" (spec 157, Persistence and Docs bullets). This brief asks whether rewording is the right answer.

### Current state: what is in `data_dir`

| File | Contents | Durability today |
|---|---|---|
| `hassette.db` (+`-wal`, `-shm`) | All 10 tables below | Treated as regenerable everywhere: docs, retention, failsafe, rollback |
| `<cache_key>/cache/cache.db` | Per-instance `cache_entries` (pickled app data, optional TTL) | Durable user data, best-effort: `AsyncCache.initialize()` deletes and recreates the file on corruption (`src/hassette/cache/wrapper.py:111-125`) |
| `.web_api_token` | Web API credential | Durable; written atomically by temp file and rename (`src/hassette/web/auth/tokens.py:151-170`); regenerated if missing |
| add-on only: `/data/backup/hassette-snapshot.db` | Consistent copy of `hassette.db` | Backup artifact (spec 129 D10) |

Two corrections to starting assumptions:

- **`cache_entries` is not in `hassette.db`.** #2695's body lists it as DB state. The cache lives in a separate file per instance (`src/hassette/app/app.py:188`, `src/hassette/cache/_helpers.py:36`), so hassette already splits a durable-ish store from telemetry.
- **Foreign keys are enforced at runtime.** `set_pragmas()` runs `PRAGMA foreign_keys = ON` on the write connection (`src/hassette/core/database_service.py:540`). Retention's NOT EXISTS guards are still the main integrity mechanism for parent rows.

### Key constraints

- Single writer: every write runs through `DatabaseService`'s queue (`submit()` awaited, `enqueue()` droppable). Spec 157 D10 builds its commit-then-publish rule on that queue.
- Spec 132 (ratified) makes the DB the UI's source of truth and wants a seeded DB file servable with no hassette instance.
- Pre-v1: clean breaks, no shims. Today no durable table exists in `hassette.db`, so a split costs no data migration **if it lands before 027.sql ships**.

## Table classification

"Origin" means where the truth lives: the thing that would rebuild the row.

| Table (migration) | Writer | Origin | Lost if the file is deleted | Retention / failsafe | Class |
|---|---|---|---|---|---|
| `executions` (001, rebuilt 009) | execution pipeline, append | process events | History only | Age (two tier targets, priorities 2 and 5); failsafe-deletable | Regenerable telemetry |
| `log_records` (001) | log persistence handler, append | process logs | Log history | Age; DEBUG rows failsafe-deletable (priority 0), INFO+ exempt | Regenerable telemetry |
| `blocking_events` (005) | command executor, append | process events | History | Age; failsafe-deletable | Regenerable telemetry |
| `api_writes` (024) | API write recorder | process events | History | Age; failsafe-deletable | Regenerable telemetry |
| `listener_misses` (025) | miss recorder, hourly rollups | process counters | History | Age on `last_ts`; failsafe-deletable; cascades with its listener | Regenerable telemetry |
| `lifecycle_events` (026) | session manager | process events | Nothing visible (no reader yet) | Age; failsafe-exempt | Regenerable telemetry |
| `sessions` (001) | session manager, one row per start | process | Nothing visible: only reader is the stale `once=True` cleanup (`session_manager.py:239`) | Parent-guard only; never failsafe | Regenerable telemetry |
| `listeners` (001…020) | upsert by natural key at registration (`repository.py:116`) | app code | Autoincrement ids shown by the CLI and UI (`hassette listener <id>`) change; retired rows' history goes | Parent-guard; never failsafe | Regenerable registration (identity) |
| `scheduled_jobs` (001…020) | upsert by natural key (`repository.py:174`) | app code; `next_run` is display-only, never read back | Same as listeners; no schedule state lost | Parent-guard; reconcile deletes jobs with no history | Regenerable registration (identity) |
| `app_manifests` (011) | upsert from config at startup and reload (`app_lifecycle_config.py:60`) | config | Removed apps drop off the grid along with the history spine | Pruned when nothing references the app | Regenerable registration (identity) |
| *Planned, spec 132:* `app_runtime`, `app_instances`, `service_status`, `session_counters` | projector | process memory (projection) | Current status until the next projector run, which is about 30s | Deleted with their session (D25) | Regenerable projection |
| *Planned, spec 155/157:* entity table (157 D4: one row per declared entity, value and attributes as JSON) | integration core service | **the DB itself** (restored to memory at startup) | **Switch values, sensor values and attributes.** Declarations come back when each instance next runs; a failed instance's last declarations (kept by spec 155 D9) are lost until it runs | Never a target (157 Persistence bullet); deleted only by D9 commit and D13 startup prune | **Durable state** |
| *Planned, #2768:* config overrides | web API write path | **the DB itself** (desired state, spec 132 D11) | **User-set config values; apps silently revert to file config** | None defined | **Durable state** |
| *Planned, #2768:* per-session effective config and provenance | at app creation | config plus overrides | Until next start | Session-scoped (D6) | Regenerable projection |
| *Possible, #1753:* failsafe stats row | failsafe | process | Failsafe history | Excluded from targets | Regenerable telemetry (meta) |

The "in-between" tables (`sessions`, `listeners`, `scheduled_jobs`, `app_manifests`) are all regenerable. What a wipe costs there is identity and history continuity: CLI ids change, and removed apps vanish from the grid. Nothing that changes runtime behavior is lost. Nothing in hassette reads a row of any of them back into process state at startup. That rests on a search for startup read-backs across `src/hassette/core/`, which found only the stale `once=True` cleanup and natural-key upserts that return ids.

## How hassette deletes or recreates the DB file today

| Trigger | Code | What happens | Effect on durable rows if they shared the file |
|---|---|---|---|
| Existing file with `user_version == 0` | `handle_schema_version`, `database_service.py:479-488` → `delete_db_files` | Auto-deletes the file, `-wal` and `-shm`. Logs "recreating database (no production data to preserve)". Raises "Cannot delete stale database file … Please remove it manually and restart" only on `PermissionError` | None. At version 0 no migration has run, so no durable table exists. The rule is safe for a state file with its own chain too |
| Schema ahead of head (rollback, downgrade) | `database_service.py:458-469` | Refuses to delete, raises `SchemaVersionError`, fatal to the process | Not deleted by code. The docs (`troubleshooting.md:188`, `:290`) tell the user to "delete the database to start fresh" → **lost** |
| Rolling back past a migration | `docs/pages/operating/upgrading.md:192`: "Rolling back past this release requires deleting the telemetry database." | Manual | **Lost** |
| Schema behind head, nonzero | `database_service.py:471-477` | Migrates in place; no delete. A failing migration raises `RuntimeError` (`migration_runner.py:113-114`) and startup fails; no backup is taken | Kept, but no backup before migrating |
| Corruption | No detection in `DatabaseService` (no `integrity_check`, no corruption match outside `cache/`) | Opening, migrating or a write fails, followed by degraded mode or a startup failure. Docs (`database-telemetry.md:203`, `db_recovery.sh`) say deleting is safe | **Lost** |
| Add-on restore | `restore_snapshot`, `database_snapshot.py:78-99` | Copies the snapshot in only when the live DB is missing; never overwrites | Restored as of the snapshot (fine) |
| App cache corruption | `cache/wrapper.py:124` | Auto-deletes and recreates that `cache.db` | n/a (separate file already) |

The 2026-06-16 rollback-safety brief's gate table is outdated. It records a behind-head auto-delete that no longer exists, so only the version-0 delete remains. Its recommended "back up before any delete or refusal" step (its Option C) was never built.

## Peer evidence

| Peer | Regenerable store | Durable store | Bad-DB policy |
|---|---|---|---|
| Home Assistant | Recorder `home-assistant_v2.db` (`purge_keep_days` default 10) | `.storage/` JSON via `Store` (`STORAGE_DIR = ".storage"`, `helpers/storage.py:41`): versioned with a `migrate_func`, optional atomic writes. Entity restore state is `core.restore_state`, dumped every 15 minutes (`STATE_DUMP_INTERVAL = timedelta(minutes=15)`, `helpers/restore_state.py:30`) and at stop | **Corrupt recorder DB:** renamed and recreated. `move_away_broken_database` logs "The system will rename the corrupt database file %s to %s in order to allow startup to proceed" (`recorder/util.py:404-423`). **Too-new schema:** the recorder alone stops, logging "either upgrade Home Assistant Core or restore the database from a backup compatible with this version" (`recorder/core.py:783-792`), and the rest of HA runs |
| ESPHome (in HA) | n/a | Entity list and device info per config entry in a HA `Store` keyed `esphome.{entry_id}` (`esphome/domain_data.py:28-37`), loaded at startup (`entry_data.py:545`) so entities exist before the device connects | n/a |
| Node-RED | Logs separate | Context store. Default `memory`: "By default, context is stored in memory only. This means its contents are cleared whenever Node-RED restarts." Optional `localfilesystem` in `~/.node-red/context`, which "only writes them out to the file-system every 30 seconds" (`flushInterval` default 30, "to minimise wear on … a Raspberry Pi's SD card") | n/a |
| NetDaemon, AppDaemon, pyscript | — | NetDaemon's old integration used HA's `.storage/netdaemon`; AppDaemon and pyscript persist nothing (`design/research/2026-11-16-app-declared-ha-entities/prior-art.md`) | — |
| Music Assistant (add-on) | `cache.db`, excluded from backups | `library.db` kept (`design/research/2026-10-10-ha-addon-conventions/web-research-config.md:160`) | — |

The peers split by data class, not by size. Every peer that persists durable state keeps it out of the file it treats as disposable. One claim in #4277 couldn't be confirmed: that HA documents the recorder DB as deletable. The recorder integration page (home-assistant.io/integrations/recorder) has no such sentence; the evidence is HA's own move-aside-and-recreate code plus common community practice. That is Supported, not Direct.

## The WAL and ATTACH finding

From SQLite's ATTACH page (https://www.sqlite.org/lang_attach.html, "Details"):

> Transactions involving multiple attached databases are atomic, assuming that the main database is not ":memory:" and the journal_mode is not WAL. If the main database is ":memory:" or if the journal_mode is WAL, then transactions continue to be atomic within each individual database file. But if the host computer crashes in the middle of a COMMIT where two or more database files are updated, some of those files might get the changes where others might not.

hassette runs WAL (`database_service.py:532`). So **a write job that touches both files is not crash-atomic**, while a job confined to one file is. No planned durable write needs to span both:

- Spec 157's running-time commit and `set()` touch only the entity table. The `RUNNING` status write is a separate step (`app_lifecycle_instances.py`), and under spec 132 the projector writes it.
- #2768's override write is desired state. Its per-session effective config is a later projection.

Other per-schema facts from https://www.sqlite.org/pragma.html that the design depends on:

- **Journal mode, all-or-one:** `journal_mode` "changes the journaling mode for 'database' or for all attached databases if 'database' is omitted". Set it after `ATTACH`, or set `PRAGMA state.journal_mode = WAL` explicitly.
- **Durability, per schema:** `PRAGMA schema.synchronous` is per schema. "A transaction committed in WAL mode with synchronous=NORMAL might roll back following a power loss or system crash." With FULL, "the extra WAL sync following each transaction helps ensure that transactions are durable across a power loss." hassette's `synchronous = NORMAL` was chosen because "this is acceptable for operational telemetry" (`database_service.py:534-538`). It is not acceptable for a switch value that HA has already displayed, so the state file should run `FULL`.
- **Defaults to main:** "If the optional schema name is omitted, 'main' is assumed." The failsafe's size measure (`PRAGMA page_count`/`freelist_count`, `database_sql.py:87-90`) and `incremental_vacuum` stay telemetry-only with no code change, provided telemetry stays `main`.
- **Snapshots, per schema:** Python's `sqlite3.Connection.backup(target, *, pages=-1, progress=None, name='main', sleep=0.25)` takes the attached schema name, so `write_snapshot` can copy each file separately.

## Feasibility analysis

### What would need to change (Option B, recommended)

| Area | Files | Effort | Risk |
|---|---|---|---|
| Second migration chain | `src/hassette/core/migration_runner.py` (take a chain directory; it already works per path and opens its own `sqlite3` connections), new `src/hassette/migrations_state/` (or `migrations_sql/state/`) | Low | Low: the runner already handles a fresh file, `auto_vacuum` and crash-safe `user_version` |
| Open, gate and attach | `database_service.py`: `resolve_db_path` plus a state path; `handle_schema_version` per file (strict for state: too-new refuses, never deletes beyond version 0); `ATTACH` on both connections; `PRAGMA state.synchronous = FULL`; journal mode after attach | Medium | `query_only` on the read connection must cover the attached schema; prototype it |
| State writes | Spec 157's core service writes `state.<table>` through the same `submit()` | Low | Rule "no job spans both schemas", pinned by a test or by repository structure |
| Snapshot and restore | `database_snapshot.py`, `database_snapshot_cli.py`, `write_shutdown_snapshot`, config for a second snapshot path | Low-Med | Add-on restore must handle each file independently |
| Add-on glue | `NodeJSmith/hassette-addon`: `backup_exclude` patterns, `backup_pre` snapshot, start-glue restore | Low (other repo) | A missed pattern hot-tars the state WAL and risks a torn restore (spec 129 D10's original problem) |
| Seeds and snapshot mode (spec 132 D4/D15/D16) | `scripts/seed_db.py`, `scripts/seed_scenarios/` | Low | Only once entity listings are seeded |
| Config | `DatabaseConfig` (derive the state path from `data_dir`, or add `database.state_path`) | Low | Open question below |
| Docs | `troubleshooting.md`, `core-concepts/database-telemetry.md`, `configuration/index.md` (data_dir inventory), `operating/upgrading.md`, add-on `operating.md`/`configuration.md` | Low | The "Safe to delete" paragraph stays true; new text covers the state file |
| Tests | DB service tests (attach, gate per file), snapshot tests, a classification test (every table of each chain is in exactly one store; retention targets name only telemetry tables) | Medium | — |

The test harness is unaffected: spec 157 already backs its core service with an in-memory store, and the harness runs no `DatabaseService`.

### What already supports this

- The migration runner is path-based and chain-agnostic in shape (`_collect_migrations`, `_read_user_version(db_path)`).
- `delete_db_files`, `write_snapshot` and `restore_snapshot` all take a path, and the backup API takes a schema name.
- The failsafe and retention already work from allow-lists (`retention_targets.py`). Unqualified pragmas measure only `main`.
- hassette already keeps durable-ish data in separate files (cache, token), so a second file under `data_dir` breaks no convention (ADR-0001 and `design/research/2026-02-16-sqlite-command-pattern/prereq-06-open-questions.md:88` accepted "separate files" for the cache).
- Spec 157's entity table has no foreign keys and needs no join to other tables for its own writes (157 D4). SQLite foreign keys can't cross attached schemas, and none is needed.

### What works against this

- **Two of everything:** two `user_version`s, two snapshot files, two add-on exclude sets. The add-on glue lives in another repo, and it is the place a miss causes the worst failure, a torn backup.
- **Spec 132's "a seeded DB file" becomes "seeded DB files".** `seed:serve` must open both files.
- **Fault coupling:** one connection attaches both files, so an unreadable state file fails the connection setup for telemetry too. This is acceptable because the state file is required anyway, but it means the split buys data isolation, not runtime isolation.
- **Low durable-state churn makes the split look premature:** one table now, overrides later. The counter-argument is timing. A split before 027 ships costs no data move. After it ships, every existing install needs a cross-file move migration.

## Options evaluated

### Option A: One file, with a declared lifecycle per table

**How it works:** `hassette.db` holds everything. A registry (an extension of `retention_targets.py`, or a sibling module) declares each table's class: telemetry, registration, projection or durable. A test asserts that every table in the chain is classified and that no retention or failsafe target names a durable table. Docs replace "Safe to delete" with "Deleting resets declared switches, sensors and config overrides." `handle_schema_version` takes a `VACUUM INTO` backup before refusing (rollback-safety Option C), and the `SchemaVersionError` and rollback docs point users at that backup instead of telling them to delete.

**Pros:**
- Smallest code change. One writer, one file, one snapshot, no add-on change.
- Cross-class queries and writes stay atomic.
- The classification registry is valuable on its own and carries over to Option B.

**Cons:**
- Every documented recovery (corruption, too-new schema, rollback) still has only a whole-file answer. Each one now costs durable state, and telemetry's frequent migrations make rollbacks across a schema change the norm, not the edge case.
- Telemetry can never get HA's move-aside policy, because moving the file aside moves the user's switches with it.
- Durable rows inherit `synchronous = NORMAL`, so a power loss can roll back a switch value HA already showed. Fixing that means `FULL` for every telemetry write.
- The user-facing promise becomes conditional ("safe, except …"), which is the thing #4277 set out to avoid.

**Effort:** Small to medium (classification test, backup-before-refuse, docs).

**Dependencies:** none.

### Option B: Second SQLite file, attached to `DatabaseService` (recommended)

**How it works:** `hassette.db` keeps every current table and spec 132's projection tables. A new `hassette-state.db` holds durable tables, starting with spec 157's entity table and later #2768's overrides. It has its own migration chain and `user_version`, and it is gated strictly: a too-new schema refuses to start, and it is never deleted beyond the version-0 rule. `DatabaseService` attaches it as `state` on both its write and read connections. That keeps one writer queue, one read connection, and cross-schema reads for #4219's listing (entity rows joined to projected instance status). Writes never span schemas.

A follow-up then gives the telemetry file HA's recorder policy: on corruption or a too-new schema, move the file aside (keeping one copy) and start fresh, logging an ERROR. That makes rollback "just work" for telemetry. The state chain changes rarely, so a rollback seldom touches it.

**Variant B2: separate connection pair or service instead of ATTACH.** This gives runtime isolation: a broken telemetry file wouldn't take state writes down. The cost is a second writer queue, heartbeat and restart policy, which duplicates `database_write_queue.py`, and #4219 loses SQL joins. That is not worth it at this scale; mention it only if runtime isolation becomes a requirement.

**Pros:**
- "Delete `hassette.db`" stays true and costs history only. Every existing recovery doc keeps working.
- Telemetry can become self-healing (move aside, HA-style) without risking user state.
- Per-file `synchronous`: power-loss durability for durable rows only.
- Matches every peer that persists state (HA `.storage`, ESPHome Store, Node-RED context store).
- Free now: no durable table exists yet.

**Cons:**
- A second chain, second snapshot and second add-on backup set, with a cross-repo change.
- Multi-file commits are not crash-atomic in WAL. This is safe only while the "no job spans both" rule holds, and needs a test.
- Seeds and snapshot mode handle two files.

**Effort:** Medium. The infrastructure is one focused PR before #4218; the move-aside policy is a separate small follow-up.

**Dependencies:** none new (stdlib `sqlite3`, aiosqlite).

### Option C: A JSON store, HA `.storage` style

**How it works:** Durable state lives in JSON files under `data_dir/.storage/` (one per concern, or one per instance), written atomically by temp file and rename like `.web_api_token`. Each file is versioned with a migrate function like HA's `Store`.

**Pros:**
- Human-readable. Hot tar backups can't tear: an atomic rename means the file is always whole, so the add-on needs no snapshot machinery for it.
- Closest to HA's own split. `tokens.py` already has the write pattern.

**Cons:**
- Spec 157 D10's commit-then-publish ordering comes from `DatabaseService`'s single writer. A JSON store needs its own serialized writer, plus a full-file rewrite and fsync on every `set()`. HA and Node-RED both batch writes (15 min, 30 s) precisely to avoid that, which would break spec 155 D6's "committed before published".
- Spec 132 wants UI reads served from a DB file, including seeded snapshot mode. A JSON store adds a second read path, and #4219 can't join entities to instance status in SQL.
- Reverses ratified text in both 155 (D6, "entity-state table in hassette's DB") and 132 (D11, "override storage lives in the DB").

**Effort:** Medium to large.

**Dependencies:** none.

### Option D: Do less, keeping spec 157 as ratified

**How it works:** Ship `027.sql` into `hassette.db`, never a retention or failsafe target, and change the "Safe to delete" paragraph to say it also resets declared switch and sensor values. This is exactly spec 157's Persistence and Docs bullets.

**Pros:** zero new work. Durable-state volume is small. A switch reset to its `initial` value and a sensor gone `unknown` are recoverable annoyances, not data loss in the financial sense.

**Cons:**
- Every cost in Option A's list, without A's classification test or backup-before-refuse.
- Three other docs pages (`database-telemetry.md:203`, `troubleshooting.md:188/:290`, `upgrading.md:192`) also say "delete", and spec 157 only names one.
- #2768 later adds overrides whose loss silently changes app behavior.
- The split stays possible later, but then needs a cross-file data move on every install.

**Effort:** Trivial.

## Effects on #2695, #1753 and #4218

**#2695 (database as a required core subsystem):**
- *Under B:* "required" covers both files, each with its own failure policy. The state file fails startup when it can't open, migrate or match its schema, and is never deleted. That is spec 157's loud-failure posture. The telemetry file is required too, but its "can't use it" path can become move-aside-and-recreate rather than a fatal stop (the follow-up).
- *Under B, naming:* #2695's rule, "use 'telemetry' only for execution/observability data", becomes literal: a telemetry file and a state file, both owned by `DatabaseService`.
- *Under B, docs:* the AC's docs rewrite ("Hassette's database") becomes "Hassette's two database files", stating what each holds and what deleting each costs.
- *Body correction:* #2695 lists `cache_entries` as DB state; it isn't. The cache is per-instance `cache.db` files, and `src/hassette/cache/` doesn't touch `DatabaseService`.
- *Under A or D:* #2695's contract ("a DB that cannot be opened … fails startup") turns corruption into a stop whose only documented fix deletes durable state.
- *Conflict to settle:* #2768 requires "a missing, unreadable, or corrupt override store degrades to file config … never prevents startup", while #2695 and spec 157 fail loudly. This needs a decision either way (Open Questions).

**#1753 (failsafe visibility):**
- Scope unchanged under every option. Its remaining ask is surfacing failsafe stats (`consecutive_size_triggers`, last run, deleted-by-table, size against `max_size_mb`) in `/health` and the UI.
- Under B, the failsafe and `max_size_mb` measure only the telemetry file with no code change, because unqualified pragmas read `main`, and the docs can say so.
- A persisted stats row belongs in the telemetry file, excluded from targets. Losing it on a recreate is fine.
- The split does not answer "could telemetry be truncated freely": the failsafe already never touches non-target tables. What it adds is a new whole-file option (move aside) for the corruption and too-new cases, not for size.

**#4218 (entity table):**
- *Under B:* the table moves from `migrations_sql/027.sql` to the state chain's first migration and is addressed as `state.<table>`.
- *Unchanged:* writes still run through `DatabaseService.submit()`, and spec 157 D10 (commit, then memory, then revision on the single writer) still holds.
- *Prune and harness:* the D13 startup prune runs against the state file, and the harness stays in-memory.
- *Docs:* the troubleshooting paragraph stays as-is. The new integration-entities page (157 D9) and the data_dir docs say where switch and sensor values live and that deleting `hassette-state.db` resets them.
- *Ordering:* #4218 gets `After:` the state-store issue.

## Recommendation

**Choose Option B and land the state store before #4218.** The evidence for the deletion argument is Direct: the four "delete the file" docs paths and the `handle_schema_version` branches are cited above. The schema-churn figure comes from `git log` on `src/hassette/migrations_sql/`. The peer pattern is Direct for HA, ESPHome and Node-RED from their source and docs. The claim that users will hit rollback-with-delete is Inferred: it follows from churn plus the documented rollback procedure, but nothing records how often the ~3 known users roll back.

**Take Option A's classification registry into B regardless.** It is what keeps a future table from landing in the wrong file or becoming a retention target.

**Where spec 155's tables live:** the entity table, holding declarations plus switch and sensor values and attributes (one table per 157 D4), goes in `hassette-state.db`. #2768's override rows go there too. Every projection and telemetry table stays in `hassette.db`, including spec 132's session-scoped tables and #2768's per-session effective config.

**How to state the model** (resolving spec 132 against spec 155):

> hassette keeps two kinds of data. **Observed state** is a projection and event log of the running process (memory → `hassette.db` → UI and CLI). It is regenerable, and deleting it costs history. **Owned state** originates in storage (`hassette-state.db` → memory at startup). Writes commit before memory changes (spec 157 D10), and deleting it costs user-visible state. The UI reads both from the database files, so spec 132's "the DB is the source of truth for what the UI shows" holds for both. Spec 132's "one-way projection" describes observed state only.

This is the Kubernetes spec/status split that spec 132 already cites for its projector. Desired state (spec) is authored and stored; status is observed and rebuildable.

**Do less if:** you judge a switch reset on DB delete or rollback acceptable for a pre-v1 tool with ~3 users. Then take Option A rather than D, since the classification test and backup-before-refuse cost little and fix the docs that D misses.

### Suggested next steps

1. Prototype the attach in a branch: aiosqlite `ATTACH` on both connections, `PRAGMA state.journal_mode = WAL`, `state.synchronous = FULL`, `query_only` on the read side, and `backup(name="state")`. Time a `set()` with FULL on slow storage.
2. File the follow-up issues below, and record the 132, 155, 157 and 129 amendments.
3. Update #4218's pickup ledger (spec 157, still on branch `4218`) before it builds: Persistence and Docs bullets, and an `After:` on the state-store issue.

## Proposed amendments

### Spec 132 (`design/specs/132-db-source-of-truth/design.md`, ratified)

Ratified is not a terminal status, so amend inline with "(Amended by spec NNN / #4277 brief: …)" markers, as D2 already does for spec 142, and add a dated `## Addendum` entry summarizing the change.

- **Summary:** add the observed-versus-owned model above. The projector, its tables and every telemetry table live in `hassette.db`; owned state lives in `hassette-state.db`, attached as `state`.
- **D6:** append that session-scoped runtime tables live in the telemetry file and never in the state file.
- **D11:** "override storage lives in the DB as desired state" → "lives in the state file as owned state; effective config plus provenance per session is a projection in the telemetry file".
- **D4, D15, D16 (seeds, snapshot mode):** seeds write both files (the state file is empty when a scenario declares no entities or overrides), and `seed:serve` opens both read-only.
- **D20:** #2695's required-DB contract covers both files, with per-file failure policy (state: fail loudly, never delete; telemetry: as #2695 decides, with move-aside as a follow-up).
- **D23:** the "database unavailable" banner covers a failure of either file. Under ATTACH, both share one connection, so one state is enough.
- **D25:** state-file tables are never retention targets or parent-guard children. Their deletion rules are domain rules (spec 155 D9, D13).
- **Assumed:** add "No write job spans both files: in WAL mode a multi-file commit is not atomic across a crash (sqlite.org/lang_attach.html)."

### Milestone #16 "DB as Source of Truth", Done-when

- "serves a seeded DB to the Vite UI" → "serves seeded database files (telemetry and, when the scenario has any, state) to the Vite UI".
- The description's "Makes the DB the source of truth…" → "Makes the database files the source of truth…".
- Add to the milestone description: "Observed state is regenerable (`hassette.db`); owned state lives in `hassette-state.db`."
- The release rule is unchanged.

### Other ledgers

- **Spec 155 (ratified):** Summary "Persistence is hassette's database" and D6/D9 "in hassette's DB" → "in hassette's state file (`hassette-state.db`)". Inline amendment plus an Addendum entry.
- **Spec 157 (ratified, branch `4218`):**
  - *Persistence bullet:* the state chain's first migration instead of `027.sql`, with `synchronous = FULL` on that schema.
  - *Docs bullet:* "Safe to delete" stays unchanged, and the integration-entities page states where values live.
  - *Assumed:* gains "the state file exists (issue N)".
- **Spec 129 (ratified):** D10 Addendum. The state file gets the same snapshot, exclude and restore treatment as `hassette.db`.
- **Specs 072, 087 (archived):** no change needed. Their "DB is disposable" assumption stays true of `hassette.db` under B.

## Proposed follow-up issues

1. **Add a durable state file beside the telemetry database.** Second SQLite file attached as `state` on `DatabaseService`'s connections; own migration chain and `user_version`; strict version gate (refuse too-new, never delete beyond version 0); `synchronous = FULL` on it; a classification test (every table in exactly one chain, retention targets only in telemetry, no write job spans both); docs for what each file holds. Blocks #4218 and #2768.
2. **Snapshot and restore the state file with the telemetry database.** `write_snapshot`, `restore_snapshot`, the CLI and the shutdown snapshot handle both files; config for the second snapshot path.
3. **(hassette-addon) Back up and restore `hassette-state.db`.** `backup_exclude` for the live state files, `backup_pre` snapshot, start-glue restore; mirrors spec 129 D10.
4. **Move a corrupt or newer-schema telemetry database aside instead of stopping.** HA recorder's `move_away_broken_database` pattern for `hassette.db` only, keeping one moved-aside copy, logged at ERROR; replaces `SchemaVersionError` for telemetry. Also drop the false "no production data to preserve" log text, and update the `SchemaVersionError`, rollback and corruption docs.
5. **Check whether add-on backups can tear app cache files.** Per-instance `cache.db` files in `/data` run in WAL and are hot-tarred by Supervisor with no snapshot (spec 129 D10 covered only `hassette.db`). Confirm, then exclude them as rebuildable or snapshot them.

Plus two issue comments rather than new issues:
- **#2695:** remove the `cache_entries` claim, add the state file to the audit, and note the per-file failure policy.
- **#2768:** override storage moves to the state file, and its "corrupt store never prevents startup" criterion needs reconciling with the state file's fail-loud policy.

## Open questions

- [ ] **needs-user:** Name and config surface for the state file. Derive it from `data_dir` (`hassette-state.db`) with no new setting, or add `database.state_path` beside `database.path`? The add-on pins `database.path`, so a derived sibling of `database.path` may be simplest.
- [ ] **needs-user:** When the state file is unreadable or corrupt, should hassette fail startup (spec 157's loud posture, #2695) or degrade to "no owned state" with an ERROR (#2768's "never prevents startup")? Each choice loses something different: availability versus switches silently reset.
- [ ] **needs-user:** Is the do-less judgment acceptable, i.e. switches and sensors reset on a rollback or DB delete for a pre-v1 tool? If yes, Option A is the floor; if no, Option B.
- [ ] **needs-prototype:** aiosqlite ATTACH on both connections, with `query_only` covering the attached schema, `journal_mode` ordering, `backup(name="state")`, and `set()` latency at `synchronous = FULL` on SD-card-class storage.
- [ ] **needs-investigation:** Whether the failsafe's unqualified `PRAGMA wal_checkpoint(TRUNCATE)` checkpoints every attached WAL file or only `main`. Either is harmless, but the failsafe docs should say which. The pragma page's checkpoint text wasn't extracted cleanly in this research.
- [ ] **needs-investigation:** Add-on app-cache backup tearing (follow-up 5). The add-on's `backup_exclude` list (spec 129 D10) names only `uv_cache` and `hassette.db*`; nothing was found that snapshots `cache.db`.
- [ ] **needs-investigation:** Whether any write planned in spec 132's issues (projector final run, session finalization) or #2768 would need to span both files. None does from reading the ledgers, but the rule should be checked at each pickup sketch.
- [ ] **Unknown, searched:** HA's official statement that the recorder DB is deletable. Not found on home-assistant.io/integrations/recorder or via an Exa search (results were community threads). The move-aside code in `recorder/util.py` is the primary evidence.

## Sources

- SQLite ATTACH: https://www.sqlite.org/lang_attach.html
- SQLite PRAGMA (`journal_mode`, `synchronous`, schema defaults): https://www.sqlite.org/pragma.html
- HA recorder corrupt-DB move-aside and too-new schema: https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/util.py, https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/core.py
- HA `Store` and restore state: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/storage.py, https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/restore_state.py
- ESPHome store: https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/domain_data.py, https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/entry_data.py
- HA recorder docs: https://www.home-assistant.io/integrations/recorder/
- Node-RED context: https://nodered.org/docs/user-guide/context, https://nodered.org/docs/api/context/store/localfilesystem
- Python `sqlite3.Connection.backup` signature: checked against the local stdlib (Python 3, SQLite 3.45.1)

Web research used `exa-search` (search and contents). The HA source files were fetched by a research subagent with Exa; its final summary was lost, so every peer claim above was re-read from the fetched source text.

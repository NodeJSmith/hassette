---
proposal: "Make telemetry DB upgrade/rollback safe so reverting to an older Hassette image no longer crash-loops with DB deletion as the only recovery."
date: 2026-06-16
status: Draft
flexibility: Exploring
motivation: "A rollback after upgrade causes a crash-loop; manual DB deletion (data loss) is the only escape. Goal: safe upgrade/rollback without manual intervention."
constraints: "Real on-disk SQLite DB for users. Any fix must not risk corrupting or losing telemetry data. Must not conflict with the recent 004/005/006 migration renumber on this branch."
non-goals: "Full Alembic-style down-migration framework; cross-version data transformation."
depth: deep
---

# Research Brief: Safe Telemetry DB Upgrade/Rollback (Issue 1050)

**Initiated by**: "v5→v6 telemetry schema migration is forward-only; older image crash-loops on a migrated DB, with manual DB deletion as the only recovery."

## Context

### What prompted this

Hassette 0.44.0 advances the telemetry DB schema to v6 (adds `mode` to `scheduled_jobs` and `listeners`, creates `blocking_events`, adds `thread_leaked` to `executions`). The migration runner is forward-only. After a 0.44.0 image migrates a user's DB to v6, rolling back to an older image makes that older image see a DB whose version is *ahead* of what it expects. It raises `SchemaVersionError`, the service is killed, and the only documented recovery is deleting the telemetry DB — discarding all historical telemetry.

### Current state

The migration and version-gate machinery is small and well-contained.

**Version source of truth** — there is no version constant. The head version is computed at runtime as `max()` of the integer-named `.sql` files in `src/hassette/migrations_sql/` (`database_service.py:441-450`, `get_expected_head_version`). Today that is `6`. The DB's own version is `PRAGMA user_version` (`migration_runner.py:60-66`).

**Apply loop** (`migration_runner.py:20-45`) — forward-only. For each `.sql` file with `version > current` and `<= target`, it runs the file inside `BEGIN IMMEDIATE ... PRAGMA user_version = N; COMMIT`. The version bump is the last statement before COMMIT, so a crash mid-migration leaves `user_version` at the previous value (crash-safe). `run_migrations` accepts a `target: int | None`, but the only caller passes `None`, so it always migrates to head. There is no down-migration, no `migrate_down`, no `down.sql` anywhere.

**The version gate** (`handle_schema_version`, `database_service.py:456-518`) is **not** a single exact-match check. It has explicit, asymmetric branches:

| DB state vs head | Action |
|---|---|
| file absent | no-op; migrations create it fresh |
| `db == head` | no-op |
| `db == 0` on an existing file | **WARN, delete DB + `-wal` + `-shm`, recreate from scratch** |
| `db < head` (non-zero) | **WARN, delete DB + `-wal` + `-shm`, recreate from scratch** |
| `db > head` | log ERROR, **raise `SchemaVersionError`** (no delete) |

Two findings here matter for the recommendation:

1. **The "ahead" branch (`db > head`) is the rollback case in the issue.** It refuses to delete and raises `SchemaVersionError`. The error name is in `DatabaseService.restart_spec.fatal_error_names` (`database_service.py:130-135`), so `ServiceWatcher` treats it as fatal: it records a fatal reason, emits a CRASHED event, and calls `hassette.shutdown()` immediately (`service_watcher.py:338-358`). **It is not technically a restart crash-loop** — it is a single immediate fatal shutdown. Under an external supervisor (Docker `restart: always`, systemd, HA add-on watchdog), that fatal exit *becomes* a crash-loop because the orchestrator keeps restarting the container, which keeps hitting the same fatal error. So the user-observed "crash-loop" is real, but its source is the external restart policy multiplying a deliberate single fatal exit.

2. **The "behind" branch (`db < head`) silently deletes the user's DB.** Its log message — "recreating database (no production data to preserve)" — is **false for any real install**. This is a pre-existing, separate data-loss bug that the same fix area touches. Today, a normal forward upgrade across a schema bump does *not* hit this branch (forward upgrades migrate incrementally on a fresh-or-current file), but any situation that lands a behind-head DB in front of newer code — a partial/aborted migration, a restored-from-old-backup file, or a downgrade-then-reupgrade — destroys telemetry without asking. The issue is framed around the rollback (ahead) case; the brief flags this adjacent deletion path because a credible fix should address both.

**Connection / mechanism facts for any fix:**
- Live connections are `aiosqlite`; the migration runner and version reads use synchronous `sqlite3` via `asyncio.to_thread` (`database_service.py:210-240`, `migration_runner.py:60-66`).
- DB path: `config.database.path` if set, else `config.data_dir / "hassette.db"` (`database_service.py:437-439`; config at `config/models.py:49`).
- Python floor is `>=3.11` (`pyproject.toml`), so the bundled SQLite is comfortably newer than 3.27 — **`VACUUM INTO` is available** on every supported runtime.
- Startup order in `on_initialize`: resolve path → `mkdir` parent → `handle_schema_version` (the gate, which may delete or raise) → `run_migrations` (thread) → open write conn → open read conn → set PRAGMAs → size failsafe → start write worker. A backup step slots cleanly **inside `handle_schema_version`, before the `db_path.unlink()` at line 510**, on whichever branch is about to delete or refuse.

### The decisive technical finding: every migration is purely additive

I read all six `.sql` files. The entire chain is `CREATE TABLE`, `CREATE INDEX`, `CREATE VIEW`, and `ALTER TABLE ADD COLUMN`. **Zero** `DROP`, `RENAME`, or type-change statements.

- `002`: `ALTER TABLE listeners ADD COLUMN cancelled_at REAL` (nullable, no default)
- `003`: `ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single' CHECK (...)`
- `004`: `ALTER TABLE executions ADD COLUMN thread_leaked INTEGER NOT NULL DEFAULT 0`
- `005`: `CREATE TABLE blocking_events (...)` + three indexes (brand-new table, soft FK to `sessions(id)`, no cascade/trigger)
- `006`: `ALTER TABLE scheduled_jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'single' CHECK (...)`

Every new NOT NULL column carries an explicit `DEFAULT`. Critically, the telemetry write code uses **explicit-column-list INSERTs** with named parameters (`telemetry_repository.py` listeners INSERT ~290-322, scheduled_jobs ~349-405, executions SQL built from an explicit column tuple ~62-70). No positional `VALUES (?, ...)`, no `INSERT ... SELECT *`. Reads use explicit column lists feeding Pydantic models that already give the new fields defaults; the only `SELECT *` is `get_log_records` (`summary_queries.py:302`), which returns raw dicts, not a validated model. None of the models set `extra='forbid'`.

**Consequence:** old code, run against a newer additive DB, is *structurally* forward-compatible. An old INSERT that omits `mode`/`thread_leaked` hits the column DEFAULT, not a constraint violation. An old SELECT names only columns it knows; extra columns are invisible. `blocking_events` is simply never referenced. The only incompatibility is the **version-number gate itself**, not the schema. The single behavioral caveat: old code would write `DEFAULT 'single'` for `mode` on rows it creates, losing overlap-mode intent for telemetry written during the rollback window — a cosmetic telemetry inaccuracy, not corruption.

This is the lever. The crash on rollback is self-imposed by an exact-`>`-rejects gate, on a schema that old code can actually read and write.

### Key constraints

- Real user DB on disk; no corruption or silent loss is acceptable. (The existing "behind" branch already violates this — see above.)
- SQLite-based; `VACUUM INTO` and the Online Backup API are both available.
- Must not renumber or collide with 004/005/006 (added on this branch today). Any new `.sql` would be `007`. The recommended options add **no** new migration file, so there is no collision risk.
- "Additive forever" is an *assumption about future migrations*, not a guarantee. A future destructive migration (DROP/RENAME/type change) would break forward-compatibility. Whatever gate we choose must fail safe when that day comes.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| Relax version gate to a supported range + declared `min_readable_version` | `database_service.py` (`handle_schema_version`, + a small constant or per-migration marker) | Low–Med | Med — correctness hinges on the additive guarantee holding for future migrations |
| Pre-delete / pre-refuse backup via `VACUUM INTO` | `database_service.py` (inside `handle_schema_version` before `unlink`) | Low | Low — pure copy, original untouched until copy succeeds |
| Fix the false "behind head" silent-delete to back up first | `database_service.py` (same branch) | Low | Low |
| Turn the fatal `SchemaVersionError` message into actionable guidance | `database_service.py` raise site + `exceptions.py` docstring | Low | Low |
| Tests: ahead/behind/backup paths | `tests/unit/test_schema_version_error.py`, `tests/integration/database/test_database_service_migrations.py` | Med | Low — harness already runs `run_migrations` on tmp DBs and asserts `user_version` |

### What already supports this

- The gate already has separate `>` / `<` / `==` branches — adding a tolerance window is editing one comparison, not rebuilding the runner.
- `run_migrations(target=...)` already exists, unused by callers — the runner can already stop at a chosen version if a future "migrate to a known-compatible target" path is ever wanted.
- Migrations are crash-safe (version bump is the last statement in the transaction), so a backup taken just before migration captures a consistent pre-migration state.
- Test harness already migrates fresh tmp DBs and asserts `PRAGMA user_version == 6` and exact column sets — extending it for a backup file or a relaxed gate is incremental.
- `VACUUM INTO` is guaranteed available given the Python floor; it requires the target file not exist (a timestamped `.bak` name satisfies that for free).

### What works against this

- The forward-compatibility argument rests entirely on migrations staying additive. Nothing in the codebase *enforces* additivity; it is a convention I verified by reading the files. A relaxed gate that trusts "additive forever" is correct today and silently wrong the first time someone writes a `DROP COLUMN`.
- `aiosqlite` for live connections vs `sqlite3` for migration/version work means a backup helper should use the same synchronous `sqlite3` + `asyncio.to_thread` pattern already in `handle_schema_version`, not the async pool.
- WAL mode: a meaningful backup must capture committed WAL content. `VACUUM INTO` and the Online Backup API both produce a consistent snapshot including WAL; a naive `shutil.copy` of just the `.db` file can miss un-checkpointed WAL pages. This rules out plain file copy as the backup mechanism.

## Options Evaluated

### Option A (recommended): Relax the gate to a declared compatibility range, and back up before any destructive action

**How it works**: Replace the exact-head logic with a supported-range check. Introduce one declared integer, `MIN_FORWARD_COMPATIBLE_VERSION` (the oldest `user_version` whose schema this code can still read/write correctly). Because every migration to date is additive, today's code can correctly operate any DB from that floor up to head — and, crucially, *newer* additive DBs too, since it only ever names columns it knows.

The gate becomes:
- `db == head`: run (no-op migrate).
- `min_compat <= db < head`: migrate up incrementally (the runner already does this) — but for the *behind* case, first take a `VACUUM INTO` backup, then migrate, never delete.
- `db > head`: this is the rollback case. If the code declares "I am forward-compatible with additive schemas," **run anyway** — old code reads the newer additive DB fine. Log a clear WARNING that the DB is newer than this binary and some newer columns/tables are ignored. Do **not** raise, do **not** delete.
- The only case that still raises is a DB that is genuinely incompatible — i.e., when a *future* migration is marked non-additive/destructive and the on-disk version crossed that boundary. That requires a per-migration "breaking" marker (a naming convention like `007_breaking.sql`, or a tiny manifest) so the gate knows which version bumps actually break forward-compat. Until such a migration exists, the destructive branch is dormant but present.

Pair this with a `VACUUM INTO` backup taken immediately before any path that would mutate or delete the file, written to `hassette.db.<headversion>-<timestamp>.bak` next to the DB. The backup is the safety net for the genuinely-incompatible future case and for the behind-head migrate path.

**Pros**:
- Fixes the actual reported failure directly: rollback to an older additive-compatible binary just works, no crash, no deletion, full telemetry preserved.
- Grounded in verified fact (every migration is additive; INSERT/SELECT name columns explicitly) rather than hope.
- Also closes the adjacent silent-delete-on-behind bug by backing up first.
- No new `.sql` migration, so zero collision with the 004/005/006 renumber.
- Small, readable diff concentrated in one method plus one declared constant.

**Cons**:
- Requires a discipline mechanism for the future: a per-migration "is this additive?" signal so the gate can correctly reject a genuinely-breaking future DB. Without it, a future destructive migration would be silently mis-tolerated. This is the real cost and must ship as part of the option (a naming convention + a check, per `encode-lessons-in-structure`).
- "Run old code on a newer DB" means telemetry written during the rollback window uses column defaults (e.g., `mode='single'`), a minor accuracy gap in historical data.
- Slightly more conceptual surface than a pure backup: maintainers must understand the additive/min-compat contract.

**Effort estimate**: Medium — the gate edit is small, but doing it *responsibly* means adding the additive-vs-breaking marker and tests for ahead/behind/breaking paths.

**Dependencies**: None new. `VACUUM INTO` is stdlib SQLite.

### Option B: Backup-only safety net (keep the gate strict, stop deleting, make the error actionable)

**How it works**: Leave the exact-head rejection on `db > head` in place — old binary still refuses to start on a newer DB — but (1) before that refusal, take a `VACUUM INTO` backup so the user has a restore point, (2) change the `SchemaVersionError` message and the `exceptions.py` docstring to tell the user exactly what happened and what to do ("this DB was written by Hassette vX; either upgrade back to >= that version, or move/delete the DB — a backup was saved at `<path>`"), and (3) on the *behind* branch, back up before the existing delete instead of silently destroying data. No change to whether old code runs on a newer DB.

**Pros**:
- Smallest behavioral change; the version contract stays "exact head only," which is conservative and trivially correct regardless of future destructive migrations.
- Eliminates the unrecoverable data-loss path: every destructive action is now preceded by a timestamped backup.
- Turns the opaque crash into a clear, actionable message — directly addresses half the motivation ("clear, actionable error").
- No reasoning about forward-compatibility required, so no risk of mis-tolerating a future breaking schema.

**Cons**:
- Does **not** fix the core complaint: rollback still won't *run*. The user can recover data, but the older image still won't start against the migrated DB. They must roll forward again or sideline the DB.
- Leaves working forward-compatibility (which actually exists today) on the table.

**Effort estimate**: Small — one backup helper, one branch reorder, message/docstring edits, and tests asserting the backup file appears before delete/refuse.

**Dependencies**: None new.

### Option C (do less): Stop the silent deletion and document the manual recovery

**How it works**: Make the two silent-delete branches (`db == 0`, `db < head`) take a `VACUUM INTO` backup before deleting, and rewrite the `SchemaVersionError` message to name the recovery steps. Do not change the gate semantics at all. Effectively Option B minus any new behavior beyond "never delete without a backup, and explain the refusal."

**Pros**:
- Tiny, obviously-safe diff. Removes the worst outcome (irreversible loss) with near-zero risk.
- A reasonable first PR that can land immediately while the range-gate design (Option A) is debated.

**Cons**:
- Rollback still crash-loops under an external restart policy; the operator still has to intervene manually (now with a backup to restore, at least).
- Doesn't use the additive forward-compat property at all.

**Effort estimate**: Small.

**Dependencies**: None.

## Concerns

### Technical risks
- **Additivity is a convention, not an invariant.** Option A's correctness depends on it. Shipping A without a structural "this migration is breaking" marker would set a trap: the first future `DROP`/`RENAME` would be silently tolerated by an old binary and could misread data. The marker (or at minimum a CI check that migrations are additive) must ship with A.
- **WAL snapshot fidelity.** The backup must use `VACUUM INTO` or the Online Backup API, never a bare file copy, or it can miss un-checkpointed WAL pages and produce a torn backup. `VACUUM INTO` also requires the target path not pre-exist — the timestamped name handles that, but the code must handle the rare collision.
- **Backup disk cost / cleanup.** Backing up before every migration accumulates `.bak` files. Need a retention rule (keep last N, or only back up on destructive/refuse paths, not on every routine forward migration) so we don't fill the data dir.

### Complexity risks
- Option A introduces a new concept users-of-the-code must hold: "supported version range + additive contract." That is more reader load than today's "exact head." Justified only if rollback-runs-clean is a real requirement; if merely *recoverable* rollback suffices, B/C are lighter.

### Maintenance risks
- A relaxed gate obligates every future migration author to declare additive-vs-breaking correctly. That is a standing tax. Encoding it as a filename convention + CI check (per `encode-lessons-in-structure`) keeps it from rotting into a comment nobody reads.
- The false "no production data to preserve" log message is itself a maintenance signal that the delete path was written assuming dev-only DBs. Any fix should delete that assumption from the code and the comments, not just add a backup around it.

## Open Questions

- [ ] Is the requirement "rollback must *run* on the old image" (→ Option A) or "rollback must be *recoverable* without losing data" (→ Option B/C)? The issue says "without manual DB deletion," which leans A, but B+actionable-error may satisfy the operational-safety motivation at much lower risk.
- [ ] Backup retention policy: back up on every migration, or only on destructive/refuse paths? How many `.bak` files to keep, and should cleanup be automatic?
- [ ] Should the backup live next to the DB (`data_dir`) or in a dedicated `backups/` subfolder? (Affects the size-failsafe and any retention sweeps.)
- [ ] For Option A's future-proofing: filename convention (`NNN_breaking.sql`) vs a small JSON manifest mapping version → additive|breaking? (Searched the repo — no existing additivity marker exists today; this would be net-new.)
- [ ] Does the HA add-on / Docker image set an external restart policy that converts the single fatal exit into the observed loop? Confirming this clarifies whether "stop crash-looping" is even in Hassette's control or is partly an orchestrator concern to document.

## Recommendation

**Ship Option C first (this PR), then decide A vs B deliberately.**

The strongest, best-supported claim in this research is *Direct*: every migration through v6 is purely additive and the read/write code names columns explicitly (verified by reading all six `.sql` files and the repository INSERT/SELECT sites). That means the rollback crash is self-imposed by an exact-`>` gate on a schema old code can actually operate. So full forward-compatibility (Option A) is genuinely achievable, not wishful.

But the most *urgent* and *lowest-risk* defect is the silent, unrecoverable deletion — both the issue's manual-deletion recovery and the adjacent `db < head` auto-delete that lies in its log message. Removing irreversible loss is unambiguously correct and independent of the harder gate-semantics debate. That is Option C, and it should land immediately with a `VACUUM INTO` backup before any delete and an actionable `SchemaVersionError` message.

Then choose between A and B on the *requirement*, not the code. If operators genuinely need an older image to **run** against a migrated DB (true zero-downtime rollback), do A — but only with a structural additive/breaking marker so it stays correct past the next destructive migration. If "recoverable without data loss" is enough, B is meaningfully safer and simpler and I would prefer it until a concrete rollback-must-run requirement appears. My honest lean: **C now, B as the likely permanent answer, A only if someone states that rollback must keep the service running** — because A's standing maintenance tax (every future migration must self-declare additivity) is real and shouldn't be paid speculatively.

On mechanism: use **`VACUUM INTO`** (guaranteed by the Python ≥3.11 floor, produces a consistent compacted snapshot including WAL, and its "target must not exist" rule is satisfied by a timestamped filename). Place the backup call **inside `handle_schema_version`, immediately before the `db_path.unlink()` at `database_service.py:510`**, on every branch that deletes or refuses. None of A/B/C adds a new `.sql` file, so none collides with the 004/005/006 renumber.

### Suggested next steps
1. Land Option C: `VACUUM INTO` backup before both silent-delete branches; rewrite the `SchemaVersionError` message and `exceptions.py` docstring to name the recovery path and the backup location; delete the false "no production data to preserve" comments. Add unit tests asserting a backup file exists before delete/refuse, keeping the existing ahead-raises and `user_version==6` tests green.
2. Run `/mine.define` on the A-vs-B decision, anchored on the requirement question (rollback must *run* vs must be *recoverable*). If A is chosen, the spec must include the additive/breaking migration marker + a CI additivity check.
3. Confirm the deployment restart policy (Docker/HA add-on) so docs can state whether the fatal exit is meant to be terminal and how operators should respond — closing the "crash-loop is partly orchestrator behavior" gap.
4. Consider `/mine.challenge` on this brief before committing to A, given A's reliance on the never-enforced additivity convention.

## Sources

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [SQLite ALTER TABLE (additive ADD COLUMN, schema-as-text compatibility)](https://sqlite.org/lang_altertable.html)
- [Alembic schema migration best practices (test downgrades; CI upgrade→downgrade→upgrade)](https://www.pingcap.com/article/best-practices-alembic-schema-migration/)
- [Database design patterns for backward compatibility (additive changes)](https://www.pingcap.com/article/database-design-patterns-for-ensuring-backward-compatibility/)
- [Confluent schema evolution & compatibility types (backward/forward/full)](https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html)
- [AWS Well-Architected: ensure backwards compatibility for schema changes](https://docs.aws.amazon.com/wellarchitected/latest/devops-guidance/dl.ads.5-ensure-backwards-compatibility-for-data-store-and-schema-changes.html)
- [Backup strategies for SQLite in production (Oldmoe)](https://oldmoe.blog/2024/04/30/backup-strategies-for-sqlite-in-production/)

---
topic: "Consistent backup of a WAL-mode SQLite DB in an HA add-on (backup_pre snapshot + restore at start)"
date: 2026-10-16
status: Draft
---

# Prior Art: SQLite Snapshot Backups in Home Assistant Add-ons

## The Problem

The add-on's telemetry DB (`/data/hassette.db`) runs in WAL mode with `synchronous=NORMAL`, so recent commits can
live only in `-wal`. Supervisor's default hot backup tars `/data` while hassette writes, and can capture the main
file and `-wal` at different moments, so a restore comes back torn. Issue #2670 implements D10 option D of
`design/specs/129-ha-addon-v01/design.md`: `backup_pre` writes a consistent snapshot to
`/data/backup/hassette-snapshot.db`, the live DB files are excluded, and a missing live DB is restored from the
snapshot at start. D10 left five mechanics open: snapshot method, temp-file handling, stale sidecars on restore,
integrity checking, and how hook failure is reported.

## How We Do It Today

Nothing yet. `docker/addon/run.sh` pins `HASSETTE__DATABASE__PATH=/data/hassette.db` and has `addon_halt` for
pre-start glue failures; there is no `backup_pre` script and no restore step. `database_service.py`'s
`delete_db_files` is the existing precedent for removing the DB together with `-wal`/`-shm`. D10's "non-zero exit
drops the whole add-on from the backup" was marked Assumed; this survey confirms it from Supervisor source.

## Patterns Found

### Pattern 1: Do nothing (hot backup of live files)

**Used by**: Vaultwarden, Grafana, Uptime Kuma, Frigate, Plex, Music Assistant (live `library.db`). Lidarr and
House Inventory exclude `-wal`/`-shm` but still ship the main file, which is worse than either extreme.
**How it works**: default `backup: hot`, no hooks; Supervisor tars the live DB while the app writes.
**Strengths**: zero code; usually works because autocheckpoint keeps the main file near-current.
**Weaknesses**: sqlite.org lists copying a DB mid-transaction as a corruption cause; failures are silent until
restore. This is the dominant baseline among popular add-ons.
**Example**: https://raw.githubusercontent.com/hassio-addons/addon-bitwarden/main/vaultwarden/config.yaml

### Pattern 2: Checkpoint in `backup_pre`, tar the live file

**Used by**: eedc, Social Home, Domely; HA core recorder adds a held write lock.
**How it works**: `PRAGMA wal_checkpoint(TRUNCATE)` folds the WAL into the main file. HA core then holds
`BEGIN IMMEDIATE` until `async_post_backup`, queueing writes in memory, so the tarred file is stable.
**Strengths**: tiny; no second file, no restore logic.
**Weaknesses**: without the write lock it only narrows the race (Social Home's config admits it "can miss the most
recent writes"); with it, writes stall for the whole backup. This is D10's rejected option B.
**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/recorder/util.py

### Pattern 3: Snapshot in `backup_pre`, exclude live files, adopt at start

**Used by**: Alarm Actions, OpenAmpere, ClearVenue, HomeHoard. Four small, unrelated projects; none official.
**How it works**: the hook uses the online backup API (Python `Connection.backup`, better-sqlite3 `db.backup`) into
a temp name in the same directory, then renames. Live DB, `-wal` and `-shm` are excluded (HomeHoard ships them too
and prefers the copy). At start, if the live DB is missing and a snapshot exists, delete stale `-wal`/`-shm` and
move or copy the snapshot into place. All four exit non-zero on failure.
**Strengths**: consistent while the app keeps writing; WAL readers don't block the writer; restore is a
file-existence check.
**Weaknesses**: a second DB copy on disk; the snapshot is from `pre` time, not tar time (HomeHoard alone closes
that gap with a write-refusal flag). A stopped add-on gets no hook, so its backup carries whatever snapshot is
already on disk.
**Example**: https://raw.githubusercontent.com/Gr33ndev/OpenAmpere/HEAD/src/openampere/ha_app.py,
https://raw.githubusercontent.com/Amantux/homehoard/HEAD/backend/backup_hook.py

### Pattern 4: Exclude the DB, accept the loss

**Used by**: SunCore; HA core users via `homeassistant_exclude_database`. This is D10's rejected option C.
No surveyed SQLite add-on uses `backup: cold`.

## Anti-Patterns

- **Excluding `-wal`/`-shm` while shipping the main DB** (Lidarr, House Inventory): drops committed transactions
  and still tars a file mid-write.
- **Checkpoint-only hook described as consistent** (eedc): it narrows the race with the tar, it doesn't close it.
- **Trusting WAL salt mismatch to protect a replaced DB**: the WAL format doesn't bind a WAL to a specific main
  file, and sqlite.org lists "overwriting a database file without deleting its hot journal" as a corruption cause.

## Relevance to Us

D10's shape is Pattern 3, which careful authors converged on independently, so the design needs no rework. The
open mechanics map onto it cleanly:

1. **Snapshot method**: `Connection.backup()` with the default `pages=-1`. It's a single step, so a concurrent
   commit can't restart it, and in WAL mode it doesn't block hassette's writer (local test on a 100 MB WAL DB:
   0.21 s, writer max commit latency 36 ms, copy passes `integrity_check`). All four snapshot peers and the
   Vaultwarden wiki use the backup API; `VACUUM INTO` is sanctioned too but needs a nonexistent target and adds
   nothing here.
2. **Temp file**: write `hassette-snapshot.db.tmp` in `/data/backup` (same filesystem, so `os.replace` is atomic),
   unlink any leftover before starting (SIGKILL skips `finally`), close the connection, then rename. The `.tmp`
   name matches none of D10's exclude patterns; it only exists mid-hook, and Supervisor tars after `pre` returns.
3. **Stale sidecars on restore**: delete `/data/hassette.db-wal` and `-shm` before placing the snapshot. sqlite.org,
   the Vaultwarden wiki, Alarm Actions and HomeHoard all say so. It's safe because the main DB is absent, so there
   is nothing for the WAL to recover into. Reuse `delete_db_files` semantics.
4. **Integrity check**: skip it. One of four peers checks; the backup API reports I/O failures as exceptions; a
   failed check at restore has no better fallback than starting empty.
5. **Hook failure**: Supervisor source confirms D10's Assumed claim. A non-zero `backup_pre` raises
   `AppPrePostBackupCommandReturnedError`, which drops only this add-on, `/config` and the user's apps included,
   from the backup; the rest of the backup completes. All four snapshot peers exit 1, on the grounds that a
   backup with stale or missing data looks exactly like one that worked. Supervisor logs hook output only at
   DEBUG, so a hook should also write its failure to the add-on log. The dropped add-on shows as "Failed apps"
   on the backup's details page, and an automatic backup raises the `automatic_backup_failed` repair issue.
6. **Stopped add-on**: Supervisor runs no hooks for a stopped add-on. With the live DB excluded, its backup
   holds whatever snapshot is on disk (Alarm Actions) or none at all (OpenAmpere, which deletes it in
   `backup_post`). HomeHoard alone covers it, by shipping the live files too and freezing writes between `pre`
   and `post` so the copy is never behind the live DB. No peer writes a snapshot on shutdown.

## Recommendation

Build D10's shape with answers 1-4 as stated. On failure policy, follow the peers and exit 1 when the DB
matters more than a stale backup is worth; D10's original exit 0 only fits a disposable DB. For the stopped
add-on, the choices are accepting a stale snapshot, HomeHoard's write freeze, or a snapshot written on clean
shutdown (no precedent, smallest change). The decisions taken are recorded in D10's 2026-10-16 addendum.

Coverage gaps: run scripts of the mainstream add-ons weren't read (config only), and Supervisor has no documented
hook timeout (none found in source either).

## Sources

Note: these URLs were not live-verified.

### Reference implementations
- https://github.com/home-assistant/supervisor/blob/main/supervisor/apps/app.py — `_backup_command`, `begin_backup`, `end_backup`
- https://github.com/home-assistant/supervisor/blob/main/supervisor/backups/backup.py — `store_apps`, per-app error capture
- https://github.com/home-assistant/supervisor/blob/main/supervisor/backups/manager.py — `_do_backup`
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/recorder/util.py — checkpoint + write lock
- https://raw.githubusercontent.com/Gr33ndev/OpenAmpere/HEAD/src/openampere/ha_app.py — backup API to `.part`, adopt at start
- https://raw.githubusercontent.com/Amantux/homehoard/HEAD/backend/backup_hook.py — tmp + quick_check + rename, sidecar delete on restore
- https://raw.githubusercontent.com/BertVanBaelen/HA-Clock-Dashboard/HEAD/alarm_actions/server/src/snapshot.ts — snapshot + restoreFromSnapshot
- https://raw.githubusercontent.com/madeByJansen/ClearVenue-HA/main/clearvenue/config.yaml — exclude list incl. temp name
- https://raw.githubusercontent.com/supernova1963/eedc-homeassistant/main/eedc/config.yaml — checkpoint-only hook
- https://raw.githubusercontent.com/social-home-io/ha-app/main/socialhome/config.yaml — checkpoint + quiesce
- https://raw.githubusercontent.com/hassio-addons/addon-bitwarden/main/vaultwarden/config.yaml — no hook
- https://raw.githubusercontent.com/hassio-addons/addon-grafana/main/grafana/config.yaml — no hook
- https://raw.githubusercontent.com/hassio-addons/addon-uptime-kuma/main/uptime-kuma/config.yaml — no hook
- https://raw.githubusercontent.com/blakeblackshear/frigate-hass-addons/main/frigate/config.yaml — no hook
- https://raw.githubusercontent.com/music-assistant/home-assistant-addon/main/music_assistant/config.yaml — live DB ships, own backup excluded
- https://raw.githubusercontent.com/hassio-addons/addon-plex/main/plex/config.yaml — no hook
- https://raw.githubusercontent.com/LeGitHubDeTai/ha_addons/main/lidarr/config.yaml — WAL excluded, main DB shipped
- https://raw.githubusercontent.com/PXLJAKE/SunCore/main/addon/suncore/config.yaml — DB excluded entirely

### Blog posts & writeups
- https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault — prefer `.backup`; delete `-wal` before restoring
- https://community.home-assistant.io/t/exclude-database-from-backup/185581 — users exclude the recorder DB

### Documentation & standards
- https://www.sqlite.org/backup.html — online backup API, restart semantics
- https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup — `pages=-1` single step
- https://www.sqlite.org/lang_vacuum.html — `VACUUM INTO`, temp-then-rename advice
- https://www.sqlite.org/howtocorrupt.html — live-DB copy methods; hot-journal corruption cause
- https://www.sqlite.org/wal.html — separating DB from WAL loses or corrupts data
- https://www.sqlite.org/fileformat2.html — WAL salts and checksums
- https://contributors.home-assistant.io/apps/reference/configuration/ — `backup`, `backup_pre`/`post`, `backup_exclude`

"""Consistent single-file snapshots of the telemetry database, and restoring one into place.

The database runs in WAL mode, so its committed state can span the main file and ``-wal``; a plain file copy
taken while hassette writes can capture the two at different moments. A snapshot is written with SQLite's
online backup API instead, which reads one consistent state while writers continue.

``DatabaseService`` writes one on shutdown when ``database.shutdown_snapshot_path`` is set, and the Home
Assistant add-on runs it from its ``backup_pre`` hook and its start glue through
``hassette.core.database_snapshot_cli`` (design/specs/129-ha-addon-v01/design.md, D10).
"""

import shutil
import sqlite3
from pathlib import Path

from hassette.utils.aiosqlite_utils import delete_db_files

# How long the snapshot's read connection waits on a locked database before failing. Matches
# _BUSY_TIMEOUT_MS in database_service.py (which imports this module, so it can't be imported here), so a
# snapshot never gives up on a lock a healthy write would wait out.
SNAPSHOT_BUSY_TIMEOUT_SECONDS = 5.0


def write_snapshot(db_path: Path, snapshot_path: Path) -> bool:
    """Write a consistent copy of ``db_path`` to ``snapshot_path``. Safe while another process writes.

    The copy goes to a ``.tmp`` sibling first and is renamed into place, so ``snapshot_path`` is always either the
    previous snapshot or a complete new one. A leftover ``.tmp`` from a run that was killed is removed first.
    The ``.tmp`` name is fixed, so two writers of the same snapshot at once (a backup hook racing a shutdown)
    can delete each other's copy; the loser raises and the previous snapshot is kept.

    Returns:
        False when ``db_path`` doesn't exist (nothing to snapshot, any previous snapshot is kept), True otherwise.

    Raises:
        sqlite3.Error, OSError: the snapshot couldn't be written; any previous snapshot is untouched.
    """
    if not db_path.is_file():
        return False
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = snapshot_path.with_name(snapshot_path.name + ".tmp")
    delete_db_files(tmp_path)
    try:
        # mode=ro so a database deleted between the check above and here raises instead of being created empty
        source = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=SNAPSHOT_BUSY_TIMEOUT_SECONDS
        )
        try:
            target = sqlite3.connect(tmp_path)
            try:
                # The default pages=-1 copies in one step, so a concurrent commit can't restart the copy.
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        tmp_path.replace(snapshot_path)
    finally:
        # removes a partial copy after a failure; nothing is left to remove after the rename
        delete_db_files(tmp_path)
    return True


def restore_snapshot(db_path: Path, snapshot_path: Path) -> bool:
    """Copy ``snapshot_path`` to ``db_path`` when the database is missing and a snapshot exists.

    A missing database next to a snapshot means a restore just happened: Supervisor deletes the add-on's data
    folder before extracting a backup, and backups exclude the live database files. A present database is never
    replaced, because the snapshot stays on disk between backups and is older than it on every ordinary start.

    Leftover ``-wal``/``-shm`` files are deleted first: SQLite would replay a WAL left beside a replaced main file
    into it. The snapshot is kept, so a later backup of a stopped add-on still carries it.

    Returns:
        True when the snapshot was restored, False when nothing needed restoring.
    """
    if db_path.exists() or not snapshot_path.is_file():
        return False
    delete_db_files(db_path)
    tmp_path = db_path.with_name(db_path.name + ".restore-tmp")
    try:
        shutil.copyfile(snapshot_path, tmp_path)
        tmp_path.replace(db_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return True

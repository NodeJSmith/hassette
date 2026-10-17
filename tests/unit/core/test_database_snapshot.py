"""Tests for hassette.core.database_snapshot: consistent snapshots of a live WAL database and restoring them."""

import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hassette.core.database_snapshot import restore_snapshot, write_snapshot
from hassette.core.database_snapshot_cli import main

# Rows committed before the snapshot starts; every one must be in it.
COMMITTED_ROWS = 200


def create_db(path: Path, rows: int) -> None:
    """Create a closed database holding ``rows`` rows in table ``t``."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row-{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def query_one(path: Path, sql: str) -> object:
    """Run ``sql`` on a read-only connection to ``path`` and return the first column of its first row."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def row_count(path: Path) -> object:
    return query_one(path, "SELECT count(*) FROM t")


def integrity(path: Path) -> object:
    return query_one(path, "PRAGMA integrity_check")


@pytest.fixture
def live_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """A WAL database with COMMITTED_ROWS rows held only in -wal by an open writer connection."""
    db = tmp_path / "hassette.db"
    writer = sqlite3.connect(db, check_same_thread=False)
    writer.execute("PRAGMA journal_mode = WAL")
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    writer.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    writer.executemany("INSERT INTO t (v) VALUES (?)", [(f"row-{i}",) for i in range(COMMITTED_ROWS)])
    writer.commit()
    return db, writer


def test_snapshot_reads_commits_still_in_the_wal(live_db: tuple[Path, sqlite3.Connection], tmp_path: Path) -> None:
    db, writer = live_db
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"
    try:
        assert Path(f"{db}-wal").stat().st_size > 0

        assert write_snapshot(db, snapshot)
    finally:
        writer.close()

    # checked before anything opens the snapshot, which would create its own -wal
    assert not Path(f"{snapshot}-wal").exists()
    assert not snapshot.with_name(snapshot.name + ".tmp").exists()
    assert row_count(snapshot) == COMMITTED_ROWS
    assert integrity(snapshot) == "ok"


def test_snapshot_is_consistent_while_a_writer_commits(
    live_db: tuple[Path, sqlite3.Connection], tmp_path: Path
) -> None:
    db, writer = live_db
    snapshot = tmp_path / "hassette-snapshot.db"
    stop = threading.Event()

    def keep_writing() -> int:
        commits = 0
        while not stop.is_set():
            writer.execute("INSERT INTO t (v) VALUES ('concurrent')")
            writer.commit()
            commits += 1
        return commits

    with ThreadPoolExecutor(max_workers=1) as pool:
        writing = pool.submit(keep_writing)
        try:
            assert write_snapshot(db, snapshot)
        finally:
            stop.set()
        writing.result(timeout=30)  # re-raises anything the writer hit
    final_rows = writer.execute("SELECT count(*) FROM t").fetchone()[0]
    writer.close()

    assert COMMITTED_ROWS <= row_count(snapshot) <= final_rows
    assert integrity(snapshot) == "ok"


def test_snapshot_skips_a_missing_database_and_keeps_the_previous_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "hassette-snapshot.db"
    snapshot.write_bytes(b"previous")

    assert not write_snapshot(tmp_path / "hassette.db", snapshot)

    assert snapshot.read_bytes() == b"previous"
    assert not (tmp_path / "hassette.db").exists()


def test_snapshot_replaces_a_leftover_temp_file(live_db: tuple[Path, sqlite3.Connection], tmp_path: Path) -> None:
    db, writer = live_db
    writer.close()
    snapshot = tmp_path / "hassette-snapshot.db"
    leftover = snapshot.with_name(snapshot.name + ".tmp")
    leftover.write_bytes(b"half-written by a killed run")
    Path(f"{leftover}-wal").write_bytes(b"stale")

    assert write_snapshot(db, snapshot)

    assert row_count(snapshot) == COMMITTED_ROWS
    assert not leftover.exists()
    assert not Path(f"{leftover}-wal").exists()


def test_failed_snapshot_keeps_the_previous_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"
    db.write_bytes(b"this is not a database" * 100)
    snapshot = tmp_path / "hassette-snapshot.db"
    snapshot.write_bytes(b"previous")

    with pytest.raises(sqlite3.DatabaseError):
        write_snapshot(db, snapshot)

    assert snapshot.read_bytes() == b"previous"
    assert not snapshot.with_name(snapshot.name + ".tmp").exists()


def test_restore_copies_the_snapshot_when_the_database_is_missing(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    create_db(source, rows=3)
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"
    write_snapshot(source, snapshot)
    db = tmp_path / "hassette.db"

    assert restore_snapshot(db, snapshot)

    assert row_count(db) == 3
    assert snapshot.is_file()


def test_restore_deletes_stale_sidecars_before_placing_the_snapshot(tmp_path: Path) -> None:
    """SQLite replays a WAL left beside a replaced main file into it, so restore removes leftover sidecars."""
    source = tmp_path / "source.db"
    create_db(source, rows=3)
    snapshot = tmp_path / "hassette-snapshot.db"
    write_snapshot(source, snapshot)
    db = tmp_path / "hassette.db"
    Path(f"{db}-wal").write_bytes(b"stale wal")
    Path(f"{db}-shm").write_bytes(b"stale shm")

    assert restore_snapshot(db, snapshot)

    assert not Path(f"{db}-wal").exists()
    assert not Path(f"{db}-shm").exists()
    assert row_count(db) == 3


def test_restore_never_replaces_an_existing_database(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"
    db.write_bytes(b"live")
    snapshot = tmp_path / "hassette-snapshot.db"
    snapshot.write_bytes(b"older snapshot")

    assert not restore_snapshot(db, snapshot)

    assert db.read_bytes() == b"live"


def test_restore_without_a_snapshot_does_nothing(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"

    assert not restore_snapshot(db, tmp_path / "hassette-snapshot.db")

    assert not db.exists()


@pytest.mark.parametrize(
    "argv",
    [[], ["snapshot", "a.db"], ["vacuum", "a.db", "b.db"]],
)
def test_main_rejects_bad_arguments(argv: list[str]) -> None:
    assert main(argv) == 2


def test_main_snapshot_failure_exits_1(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"
    db.write_bytes(b"this is not a database" * 100)

    assert main(["snapshot", str(db), str(tmp_path / "hassette-snapshot.db")]) == 1


def test_main_snapshot_and_restore_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"
    create_db(db, rows=3)
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"

    assert main(["snapshot", str(db), str(snapshot)]) == 0
    db.unlink()
    assert main(["restore", str(db), str(snapshot)]) == 0

    assert row_count(db) == 3


def test_main_succeeds_when_there_is_nothing_to_do(tmp_path: Path) -> None:
    db = tmp_path / "hassette.db"
    snapshot = tmp_path / "hassette-snapshot.db"

    assert main(["snapshot", str(db), str(snapshot)]) == 0
    assert main(["restore", str(db), str(snapshot)]) == 0

    assert not db.exists()
    assert not snapshot.exists()


def test_main_restore_failure_exits_1(tmp_path: Path) -> None:
    snapshot = tmp_path / "hassette-snapshot.db"
    snapshot.write_bytes(b"snapshot")
    db = tmp_path / "no-such-dir" / "hassette.db"  # the copy can't be written here

    assert main(["restore", str(db), str(snapshot)]) == 1


def test_module_entry_point_writes_and_restores(tmp_path: Path) -> None:
    """The add-on's backup_pre.sh and run.sh call the module with `python -m`."""
    source = tmp_path / "hassette.db"
    create_db(source, rows=3)
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"
    module = [sys.executable, "-m", "hassette.core.database_snapshot_cli"]

    subprocess.run([*module, "snapshot", str(source), str(snapshot)], check=True, timeout=60)
    source.unlink()
    subprocess.run([*module, "restore", str(source), str(snapshot)], check=True, timeout=60)

    assert row_count(source) == 3

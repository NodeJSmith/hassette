"""Telemetry DB fixtures for tests/unit/core/."""

import shutil
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.telemetry.repository import TelemetryRepository

# Minimal DDL for telemetry tests — intentionally omits many real columns.
# See test_database_service_migrations.py for the canonical schema contract.
TELEMETRY_TEST_DDL = """
CREATE TABLE log_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seq             INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    level           TEXT NOT NULL,
    logger_name     TEXT NOT NULL,
    func_name       TEXT,
    lineno          INTEGER,
    message         TEXT NOT NULL,
    exc_info        TEXT,
    app_key         TEXT,
    instance_name   TEXT,
    instance_index  INTEGER,
    execution_id    TEXT,
    source_tier     TEXT
);
CREATE INDEX idx_lr_time ON log_records(timestamp);
CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);

CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL NOT NULL DEFAULT 0,
    last_heartbeat_at     REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    name                  TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    topic                 TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    mode                  TEXT NOT NULL DEFAULT 'single',
    retired_at            REAL
);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT NOT NULL,
    instance_index        INTEGER NOT NULL DEFAULT 0,
    job_name              TEXT NOT NULL DEFAULT '',
    handler_method        TEXT NOT NULL DEFAULT '',
    source_location       TEXT NOT NULL DEFAULT '',
    retired_at            REAL,
    mode                  TEXT NOT NULL DEFAULT 'single'
);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT NOT NULL DEFAULT 'handler',
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL DEFAULT 0,
    execution_start_ts    REAL NOT NULL,
    duration_ms           REAL NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'success',
    thread_leaked         INTEGER NOT NULL DEFAULT 0,
    execution_id          TEXT UNIQUE
);

CREATE TABLE blocking_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER REFERENCES sessions(id),
    app_key          TEXT,
    instance_name    TEXT,
    instance_index   INTEGER,
    execution_id     TEXT,
    tier             TEXT NOT NULL
        CHECK (tier IN ('watchdog', 'monkeypatch')),
    primitive        TEXT,
    source_location  TEXT,
    stall_duration_ms REAL,
    detected_ts      REAL NOT NULL,
    source_tier      TEXT NOT NULL
        CHECK (source_tier IN ('app', 'framework')),
    reason           TEXT
        CHECK (reason IN ('attributed', 'framework', 'displaced'))
);
CREATE INDEX idx_be_ts      ON blocking_events(detected_ts);
CREATE INDEX idx_be_app_ts  ON blocking_events(app_key, detected_ts);
CREATE INDEX idx_be_session ON blocking_events(session_id);
"""


@pytest.fixture
async def telemetry_db(_migrated_db_template: Path, tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Migrated SQLite connection with FK enforcement on."""
    dst = tmp_path / "hassette.db"
    shutil.copy2(_migrated_db_template, dst)
    async with aiosqlite.connect(dst) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn


@pytest.fixture
async def telemetry_repo(telemetry_db: aiosqlite.Connection) -> TelemetryRepository:
    """TelemetryRepository backed by a migrated, on-disk SQLite connection."""
    mock_db_service = MagicMock()
    mock_db_service.db = telemetry_db
    return TelemetryRepository(mock_db_service)


@pytest.fixture
async def telemetry_session_id(telemetry_db: aiosqlite.Connection) -> int:
    """Insert a session row and return its ID (needed for FK constraints)."""
    # dup-ignore-start: two tests in test_telemetry_repository.py (the once=True/previous-session
    # reconciliation tests) deliberately insert a SECOND session row with this same SQL, distinct
    # from the one this fixture provides, to simulate reconciliation running against a newer
    # session. Promoting a shared helper out of this fixture for that one cross-file cluster is
    # out of scope (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py
    # helpers per task).
    now = time.time()
    cursor = await telemetry_db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await telemetry_db.commit()
    assert cursor.lastrowid is not None
    # dup-ignore-end
    return cursor.lastrowid

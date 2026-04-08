"""Fresh unified schema: source_tier on all tables, nullable FKs, is_di_failure flag.

Replaces migrations 001-006 with a single clean schema. This migration strategy is
destructive — the DatabaseService auto-recreates the DB when a version mismatch is
detected, so backward compatibility is not required.

New columns vs prior schema:
- ``source_tier TEXT NOT NULL`` (with CHECK constraint) on all 5 tables
- ``is_di_failure INTEGER NOT NULL DEFAULT 0`` on handler_invocations and job_executions
- ``listener_id`` / ``job_id`` FKs are nullable (were NOT NULL in migration 001)
- CHECK constraints on ``status`` and ``duration_ms`` in handler_invocations / job_executions
- CHECK constraint on ``status`` in sessions
- 4 new filtered views split by source_tier; 2 backward-compat aliases

Revision ID: 007
Revises: None
"""

from alembic import op
from sqlalchemy import text

revision = "007"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable incremental auto-vacuum. Must be set before any tables exist for a fresh DB.
    # For an existing DB (unlikely given the destructive strategy), VACUUM activates it.
    conn = op.get_bind()
    result = conn.execute(text("PRAGMA auto_vacuum"))
    current_mode = result.scalar()
    if current_mode != 2:
        conn.execute(text("PRAGMA auto_vacuum = INCREMENTAL"))
        conn.execute(text("VACUUM"))

    # -------------------------------------------------------------------------
    # sessions
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE sessions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at            REAL    NOT NULL,
            stopped_at            REAL,
            last_heartbeat_at     REAL    NOT NULL,
            status                TEXT    NOT NULL
                CHECK (status IN ('running', 'stopped', 'crashed', 'success', 'failure', 'unknown')),
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT,
            source_tier           TEXT    NOT NULL DEFAULT 'framework'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    # -------------------------------------------------------------------------
    # listeners
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE listeners (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            app_key               TEXT    NOT NULL,
            instance_index        INTEGER NOT NULL,
            handler_method        TEXT    NOT NULL,
            topic                 TEXT    NOT NULL,
            debounce              REAL,
            throttle              REAL,
            once                  INTEGER NOT NULL DEFAULT 0,
            priority              INTEGER NOT NULL DEFAULT 0,
            predicate_description TEXT,
            human_description     TEXT,
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            name                  TEXT,
            retired_at            REAL,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_listeners_natural
            ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
            WHERE once = 0
    """)

    # -------------------------------------------------------------------------
    # scheduled_jobs
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE scheduled_jobs (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            app_key               TEXT    NOT NULL,
            instance_index        INTEGER NOT NULL,
            job_name              TEXT    NOT NULL,
            handler_method        TEXT    NOT NULL,
            trigger_type          TEXT,
            trigger_value         TEXT,
            repeat                INTEGER NOT NULL DEFAULT 0,
            args_json             TEXT    NOT NULL DEFAULT '[]',
            kwargs_json           TEXT    NOT NULL DEFAULT '{}',
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            retired_at            REAL,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_scheduled_jobs_natural
            ON scheduled_jobs(app_key, instance_index, job_name)
    """)

    # -------------------------------------------------------------------------
    # handler_invocations
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL
                CHECK (duration_ms >= 0.0),
            status                TEXT    NOT NULL
                CHECK (status IN ('success', 'error', 'cancelled')),
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT,
            is_di_failure         INTEGER NOT NULL DEFAULT 0,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    # -------------------------------------------------------------------------
    # job_executions
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL
                CHECK (duration_ms >= 0.0),
            status                TEXT    NOT NULL
                CHECK (status IN ('success', 'error', 'cancelled')),
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT,
            is_di_failure         INTEGER NOT NULL DEFAULT 0,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")

    # -------------------------------------------------------------------------
    # Views — split by source_tier + backward-compat aliases
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE VIEW active_app_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'app'
    """)
    op.execute("""
        CREATE VIEW active_framework_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'framework'
    """)
    op.execute("""
        CREATE VIEW active_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL
    """)

    op.execute("""
        CREATE VIEW active_app_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'app'
    """)
    op.execute("""
        CREATE VIEW active_framework_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'framework'
    """)
    op.execute("""
        CREATE VIEW active_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_listeners")
    op.execute("DROP VIEW IF EXISTS active_framework_listeners")
    op.execute("DROP VIEW IF EXISTS active_app_listeners")

    op.execute("DROP TABLE IF EXISTS job_executions")
    op.execute("DROP TABLE IF EXISTS handler_invocations")
    op.execute("DROP TABLE IF EXISTS scheduled_jobs")
    op.execute("DROP TABLE IF EXISTS listeners")
    op.execute("DROP TABLE IF EXISTS sessions")

"""Add 'timed_out' to status CHECK constraints on handler_invocations and job_executions.

Extends the allowed status values from ``('success', 'error', 'cancelled')`` to
``('success', 'error', 'cancelled', 'timed_out')`` on both execution-tracking tables.

SQLite cannot modify CHECK constraints via ALTER TABLE, so this migration uses
the table-recreation pattern (same as migrations 002, 003, and 004).

Revision ID: 005
Revises: 004
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Atomicity provided by Alembic's outer transaction (see migration 002 comment).

    # -------------------------------------------------------------------------
    # handler_invocations
    # -------------------------------------------------------------------------

    op.execute("""
        CREATE TABLE handler_invocations_005 (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL
                CHECK (duration_ms >= 0.0),
            status                TEXT    NOT NULL
                CHECK (status IN ('success', 'error', 'cancelled', 'timed_out')),
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT,
            is_di_failure         INTEGER NOT NULL DEFAULT 0,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("""
        INSERT INTO handler_invocations_005 (
            id, listener_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        )
        SELECT
            id, listener_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        FROM handler_invocations
    """)

    op.execute("DROP TABLE handler_invocations")
    op.execute("ALTER TABLE handler_invocations_005 RENAME TO handler_invocations")

    # Recreate indexes (they were dropped with the original table).
    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")
    op.execute("CREATE INDEX idx_hi_source_tier_time ON handler_invocations(source_tier, execution_start_ts DESC)")

    # -------------------------------------------------------------------------
    # job_executions
    # -------------------------------------------------------------------------

    op.execute("""
        CREATE TABLE job_executions_005 (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL
                CHECK (duration_ms >= 0.0),
            status                TEXT    NOT NULL
                CHECK (status IN ('success', 'error', 'cancelled', 'timed_out')),
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT,
            is_di_failure         INTEGER NOT NULL DEFAULT 0,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework'))
        )
    """)

    op.execute("""
        INSERT INTO job_executions_005 (
            id, job_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        )
        SELECT
            id, job_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        FROM job_executions
    """)

    op.execute("DROP TABLE job_executions")
    op.execute("ALTER TABLE job_executions_005 RENAME TO job_executions")

    # Recreate indexes (they were dropped with the original table).
    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")
    op.execute("CREATE INDEX idx_je_source_tier_time ON job_executions(source_tier, execution_start_ts DESC)")


def downgrade() -> None:
    # -------------------------------------------------------------------------
    # handler_invocations — revert to 004 schema (no 'timed_out')
    # -------------------------------------------------------------------------

    # Reclassify any 'timed_out' rows as 'error' before recreating with the
    # old CHECK constraint. This avoids data loss from the downgrade.
    op.execute("UPDATE handler_invocations SET status = 'error' WHERE status = 'timed_out'")

    op.execute("""
        CREATE TABLE handler_invocations_004 (
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

    op.execute("""
        INSERT INTO handler_invocations_004 (
            id, listener_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        )
        SELECT
            id, listener_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        FROM handler_invocations
    """)

    op.execute("DROP TABLE handler_invocations")
    op.execute("ALTER TABLE handler_invocations_004 RENAME TO handler_invocations")

    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")
    op.execute("CREATE INDEX idx_hi_source_tier_time ON handler_invocations(source_tier, execution_start_ts DESC)")

    # -------------------------------------------------------------------------
    # job_executions — revert to 004 schema (no 'timed_out')
    # -------------------------------------------------------------------------

    op.execute("UPDATE job_executions SET status = 'error' WHERE status = 'timed_out'")

    op.execute("""
        CREATE TABLE job_executions_004 (
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

    op.execute("""
        INSERT INTO job_executions_004 (
            id, job_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        )
        SELECT
            id, job_id, session_id, execution_start_ts, duration_ms,
            status, error_type, error_message, error_traceback,
            is_di_failure, source_tier
        FROM job_executions
    """)

    op.execute("DROP TABLE job_executions")
    op.execute("ALTER TABLE job_executions_004 RENAME TO job_executions")

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")
    op.execute("CREATE INDEX idx_je_source_tier_time ON job_executions(source_tier, execution_start_ts DESC)")

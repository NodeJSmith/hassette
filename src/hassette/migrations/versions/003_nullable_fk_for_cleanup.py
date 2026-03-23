"""Make listener_id and job_id nullable with ON DELETE SET NULL.

This allows stale listener/job rows to be deleted at app startup without
losing invocation/execution history. Orphaned history rows (NULL parent ID)
remain queryable by session_id.

Revision ID: 003
Revises: 002
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ALTER column constraints in-place.
    # Rebuild both tables with the updated FK definitions using raw SQL.
    # This is the most reliable approach for SQLite FK changes.

    # --- handler_invocations ---
    op.execute("ALTER TABLE handler_invocations RENAME TO _handler_invocations_old")
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO handler_invocations
        SELECT * FROM _handler_invocations_old
    """)
    op.execute("DROP TABLE _handler_invocations_old")

    # Recreate indexes dropped with the old table
    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    # --- job_executions ---
    op.execute("ALTER TABLE job_executions RENAME TO _job_executions_old")
    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO job_executions
        SELECT * FROM _job_executions_old
    """)
    op.execute("DROP TABLE _job_executions_old")

    # Recreate indexes dropped with the old table
    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")


def downgrade() -> None:
    # Restore NOT NULL constraint and remove ON DELETE SET NULL.
    op.execute("ALTER TABLE handler_invocations RENAME TO _handler_invocations_old")
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER NOT NULL REFERENCES listeners(id),
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO handler_invocations
        SELECT * FROM _handler_invocations_old
        WHERE listener_id IS NOT NULL
    """)
    op.execute("DROP TABLE _handler_invocations_old")

    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    op.execute("ALTER TABLE job_executions RENAME TO _job_executions_old")
    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER NOT NULL REFERENCES scheduled_jobs(id),
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO job_executions
        SELECT * FROM _job_executions_old
        WHERE job_id IS NOT NULL
    """)
    op.execute("DROP TABLE _job_executions_old")

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")

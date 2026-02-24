"""Initial schema: sessions, listeners, scheduled_jobs, handler_invocations, job_executions.

Revision ID: 001
Revises: None
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sessions — framework lifecycle tracking
    op.execute("""
        CREATE TABLE sessions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at            REAL    NOT NULL,
            stopped_at            REAL,
            last_heartbeat_at     REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)

    # Listeners — bus event listener registrations (parent table)
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
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            first_registered_at   REAL    NOT NULL,
            last_registered_at    REAL    NOT NULL,
            UNIQUE (app_key, instance_index, handler_method, topic)
        )
    """)

    # Scheduled jobs — scheduled job registrations (parent table)
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
            first_registered_at   REAL    NOT NULL,
            last_registered_at    REAL    NOT NULL,
            UNIQUE (app_key, instance_index, job_name)
        )
    """)

    # Handler invocations — per-invocation record for bus event handlers
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

    # Job executions — per-execution record for scheduled jobs
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

    # Indexes on handler_invocations
    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    # Indexes on job_executions
    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_executions")
    op.execute("DROP TABLE IF EXISTS handler_invocations")
    op.execute("DROP TABLE IF EXISTS scheduled_jobs")
    op.execute("DROP TABLE IF EXISTS listeners")
    op.execute("DROP TABLE IF EXISTS sessions")

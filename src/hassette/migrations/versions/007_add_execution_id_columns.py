"""Add execution_id, trigger_context_id, and trigger_origin columns.

These columns allow telemetry records to be correlated with specific execution
instances (execution_id) and the triggering events (trigger_context_id,
trigger_origin). All columns are nullable TEXT — absence of population is
valid for records that pre-date this migration or for job executions which
are not event-triggered.

Column additions:
- handler_invocations: execution_id, trigger_context_id, trigger_origin
- job_executions: execution_id

SQLite supports ALTER TABLE ADD COLUMN for nullable columns with no server
default, so table recreation is not required here.

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("handler_invocations", sa.Column("execution_id", sa.Text(), nullable=True))
    op.add_column("handler_invocations", sa.Column("trigger_context_id", sa.Text(), nullable=True))
    op.add_column("handler_invocations", sa.Column("trigger_origin", sa.Text(), nullable=True))
    op.add_column("job_executions", sa.Column("execution_id", sa.Text(), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_hi_execution_id "
        "ON handler_invocations(execution_id) WHERE execution_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_je_execution_id "
        "ON job_executions(execution_id) WHERE execution_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_hi_execution_id")
    op.execute("DROP INDEX IF EXISTS uq_je_execution_id")

    op.execute("""
        CREATE TABLE handler_invocations_006 (
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
        INSERT INTO handler_invocations_006 (
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
    op.execute("ALTER TABLE handler_invocations_006 RENAME TO handler_invocations")

    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")
    op.execute("CREATE INDEX idx_hi_source_tier_time ON handler_invocations(source_tier, execution_start_ts DESC)")

    op.execute("""
        CREATE TABLE job_executions_006 (
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
        INSERT INTO job_executions_006 (
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
    op.execute("ALTER TABLE job_executions_006 RENAME TO job_executions")

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")
    op.execute("CREATE INDEX idx_je_source_tier_time ON job_executions(source_tier, execution_start_ts DESC)")

"""Add log_records table for database persistence of log records.

Stores log records emitted during handler invocations and job executions,
including correlation identifiers, app identity, and source tier. Supports
time-based retention and per-execution queries.

Indexes:
- idx_lr_time: supports time-range queries and retention cleanup
- idx_lr_exec: partial index for per-execution log lookup (execution_id IS NOT NULL)
- idx_lr_app_time: supports per-app log queries ordered by time

Revision ID: 009
Revises: 008
"""

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
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
        )
    """)
    op.execute("CREATE INDEX idx_lr_time ON log_records(timestamp)")
    op.execute("CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL")
    op.execute("CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lr_app_time")
    op.execute("DROP INDEX IF EXISTS idx_lr_exec")
    op.execute("DROP INDEX IF EXISTS idx_lr_time")
    op.execute("DROP TABLE IF EXISTS log_records")

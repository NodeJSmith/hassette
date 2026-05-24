"""Add composite indexes for status-filtered handler and job queries.

Supports the ROW_NUMBER() CTE pattern used by get_listener_summary,
get_job_summary, and get_all_jobs_summary for last-error lookups.

Revision ID: 010
Revises: 009
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_hi_listener_status_time ON handler_invocations(listener_id, status, execution_start_ts DESC)"
    )
    op.execute("CREATE INDEX idx_je_job_status_time ON job_executions(job_id, status, execution_start_ts DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_je_job_status_time")
    op.execute("DROP INDEX IF EXISTS idx_hi_listener_status_time")

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


def downgrade() -> None:
    raise NotImplementedError("migration is not reversible — execution_id data would be lost")

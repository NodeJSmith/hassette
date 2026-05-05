"""Add name_auto column to scheduled_jobs table.

Tracks whether a job's name was auto-generated from the callable and trigger
ID (True) or explicitly provided by the user (False). The frontend uses this
to prompt users to provide descriptive names.

Column default: 0 (False) — existing jobs are assumed to have user-provided
names since we can't retroactively distinguish them.

Revision ID: 008
Revises: 007
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scheduled_jobs", sa.Column("name_auto", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "name_auto")

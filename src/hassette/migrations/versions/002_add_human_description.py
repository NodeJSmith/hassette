"""Add human_description column to listeners table.

Revision ID: 002
Revises: 001
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE listeners ADD COLUMN human_description TEXT")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN before 3.35.0; use batch mode.
    with op.batch_alter_table("listeners") as batch_op:
        batch_op.drop_column("human_description")

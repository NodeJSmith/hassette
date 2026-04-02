"""Enable incremental auto_vacuum for disk space reclamation.

SQLite only reclaims disk space after DELETEs if auto_vacuum is enabled.
This PRAGMA must be set before the first table is created, so existing
databases need a one-time conversion via VACUUM.

Revision ID: 005
Revises: 004
"""

from logging import getLogger

from alembic import op
from sqlalchemy import text

LOGGER = getLogger(__name__)

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(text("PRAGMA auto_vacuum"))
    current_mode = result.scalar()

    if current_mode == 2:
        LOGGER.info("auto_vacuum is already INCREMENTAL (2); skipping conversion")
        return

    LOGGER.info("Converting auto_vacuum from %s to INCREMENTAL (2); running VACUUM", current_mode)
    # PRAGMA auto_vacuum must be set before VACUUM to take effect
    conn.execute(text("PRAGMA auto_vacuum = INCREMENTAL"))
    # VACUUM rewrites the database file, activating the new auto_vacuum mode
    conn.execute(text("VACUUM"))


def downgrade() -> None:
    # auto_vacuum mode changes are irreversible without a full VACUUM back to
    # the original mode. Leaving as INCREMENTAL is harmless, so this is a no-op.
    pass

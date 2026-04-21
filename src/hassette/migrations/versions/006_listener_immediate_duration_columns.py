"""Add immediate, duration, and entity_id columns to listeners table.

These columns track whether a listener uses the immediate-fire feature,
how long the entity must hold state before firing (duration), and which
entity the listener monitors (entity_id).

Column defaults for backward compatibility:
- immediate: INTEGER NOT NULL DEFAULT 0 (False)
- duration: REAL DEFAULT NULL (nullable)
- entity_id: TEXT DEFAULT NULL (nullable)

SQLite supports ALTER TABLE ADD COLUMN for nullable columns with defaults,
so table recreation is not required here.

Revision ID: 006
Revises: 005
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listeners", sa.Column("immediate", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("listeners", sa.Column("duration", sa.Float(), nullable=True))
    op.add_column("listeners", sa.Column("entity_id", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions, but SQLite 3.35+ does.
    # Use the table-recreation pattern for maximum compatibility.

    # Drop views that SELECT * from listeners before renaming/dropping.
    op.execute("DROP VIEW IF EXISTS active_listeners")
    op.execute("DROP VIEW IF EXISTS active_framework_listeners")
    op.execute("DROP VIEW IF EXISTS active_app_listeners")

    op.execute("""
        CREATE TABLE listeners_005 (
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
            human_description     TEXT,
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            name                  TEXT,
            retired_at            REAL,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework')),
            CHECK ((app_key != '__hassette__' AND app_key NOT GLOB '__hassette__.*') OR source_tier = 'framework')
        )
    """)

    op.execute("""
        INSERT INTO listeners_005 (
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source, name, retired_at, source_tier
        )
        SELECT
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source, name, retired_at, source_tier
        FROM listeners
    """)

    op.execute("DROP TABLE listeners")
    op.execute("ALTER TABLE listeners_005 RENAME TO listeners")

    op.execute("CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_listeners_natural
            ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
            WHERE once = 0
    """)

    op.execute("""
        CREATE VIEW active_app_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'app'
    """)
    op.execute("""
        CREATE VIEW active_framework_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'framework'
    """)
    op.execute("""
        CREATE VIEW active_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL
    """)

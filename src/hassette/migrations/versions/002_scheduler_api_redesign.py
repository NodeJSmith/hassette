"""Scheduler API redesign: add trigger_label/trigger_detail, constrain trigger_type.

Adds two new columns to ``scheduled_jobs``:
- ``trigger_label TEXT NOT NULL DEFAULT ''``
- ``trigger_detail TEXT``

Also adds a CHECK constraint on ``trigger_type`` to limit it to known values.
SQLite cannot add constraints via ALTER TABLE, so the migration uses the
table-recreation pattern: create a replacement table, copy data, drop the
original, rename.

Intentional deviation from spec: the WP spec suggested Alembic's
``batch_alter_table`` helper; explicit DDL is used instead because it gives
full control over the intermediate table name and copy SELECT list, avoiding
the risk of ``batch_alter_table`` generating a ``SELECT *`` that silently
omits or reorders columns.  The end result is semantically identical.

Revision ID: 002
Revises: 001
"""

import logging

from alembic import op
from sqlalchemy import text

LOGGER = logging.getLogger(__name__)

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This table swap is safe because DatabaseService._run_migrations() runs via
    # asyncio.to_thread() during on_initialize(), before the aiosqlite connection is
    # opened. No other writers or readers are active during migration.
    #
    # Atomicity is provided by Alembic's env.py ``context.begin_transaction()`` —
    # the entire migration runs inside a single transaction. An explicit
    # ``BEGIN EXCLUSIVE`` here would nest a second transaction, which SQLite
    # rejects, so we rely on the outer Alembic-managed transaction.

    # Drop views that SELECT * from scheduled_jobs — must be dropped before
    # renaming/dropping the underlying table so SQLite does not leave dangling
    # view references (behaviour varies by SQLite version).
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

    # Create the replacement table with the new schema.  The table name
    # ``scheduled_jobs_002`` avoids collision with the existing table during
    # the rename window.
    op.execute("""
        CREATE TABLE scheduled_jobs_002 (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            app_key               TEXT    NOT NULL,
            instance_index        INTEGER NOT NULL,
            job_name              TEXT    NOT NULL,
            handler_method        TEXT    NOT NULL,
            trigger_type          TEXT
                CHECK (trigger_type IN ('interval', 'cron', 'once', 'after', 'custom')),
            trigger_label         TEXT    NOT NULL DEFAULT '',
            trigger_detail        TEXT,
            repeat                INTEGER NOT NULL DEFAULT 0,
            args_json             TEXT    NOT NULL DEFAULT '[]',
            kwargs_json           TEXT    NOT NULL DEFAULT '{}',
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            retired_at            REAL,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework')),
            CHECK (app_key != '__hassette__' OR source_tier = 'framework')
        )
    """)

    # Copy all existing rows; backfill new columns with their defaults.
    op.execute("""
        INSERT INTO scheduled_jobs_002 (
            id, app_key, instance_index, job_name, handler_method,
            trigger_type,
            trigger_label, trigger_detail,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier
        )
        SELECT
            id, app_key, instance_index, job_name, handler_method,
            trigger_type,
            '' AS trigger_label, NULL AS trigger_detail,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_002 RENAME TO scheduled_jobs")

    # Recreate indexes (they were dropped with the original table).
    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_scheduled_jobs_natural
            ON scheduled_jobs(app_key, instance_index, job_name)
    """)

    # Recreate the three views.
    op.execute("""
        CREATE VIEW active_app_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'app'
    """)
    op.execute("""
        CREATE VIEW active_framework_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'framework'
    """)
    op.execute("""
        CREATE VIEW active_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL
    """)


def downgrade() -> None:
    # Warn about data loss: trigger_label and trigger_detail cannot be recovered after downgrade.
    conn = op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM scheduled_jobs"))
    row_count = result.scalar() or 0
    LOGGER.warning(
        "Downgrade 002→001: %d rows will permanently lose trigger_label/trigger_detail data",
        row_count,
    )

    # Atomicity provided by Alembic's outer transaction (see upgrade() comment).

    # Drop views first (same reason as in upgrade).
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

    # Recreate original schema (matching 001) without trigger_label/trigger_detail
    # and without the CHECK constraint on trigger_type.
    op.execute("""
        CREATE TABLE scheduled_jobs_001 (
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
            retired_at            REAL,
            source_tier           TEXT    NOT NULL DEFAULT 'app'
                CHECK (source_tier IN ('app', 'framework')),
            CHECK (app_key != '__hassette__' OR source_tier = 'framework')
        )
    """)

    # Copy rows back; trigger_value was dropped from the 002 schema so insert NULL.
    op.execute("""
        INSERT INTO scheduled_jobs_001 (
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, trigger_value,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier
        )
        SELECT
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, NULL AS trigger_value,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_001 RENAME TO scheduled_jobs")

    # Recreate indexes.
    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_scheduled_jobs_natural
            ON scheduled_jobs(app_key, instance_index, job_name)
    """)

    # Recreate views.
    op.execute("""
        CREATE VIEW active_app_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'app'
    """)
    op.execute("""
        CREATE VIEW active_framework_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'framework'
    """)
    op.execute("""
        CREATE VIEW active_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL
    """)

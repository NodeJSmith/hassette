"""Scheduler frontend columns: add group and cancelled_at to scheduled_jobs.

Adds two new columns to ``scheduled_jobs``:
- ``"group" TEXT NULL`` — scheduler group name, persisted at job registration.
  ``group`` is a SQLite reserved keyword and must be double-quoted in DDL/DML.
- ``cancelled_at REAL NULL`` — Unix epoch float set when a job is cancelled;
  provides a durable signal that survives heap removal.

The ``repeat`` column is intentionally preserved in the schema (it remains 0
for all new-style jobs) because removing it would require a follow-on migration
that does nothing useful and risks data loss on downgrade.

SQLite cannot add nullable columns with non-constant defaults via ALTER TABLE
when the table has constraints (CHECK, etc.), and the project convention is to
use the table-recreation pattern for schema changes (see migration 002).  This
migration follows the same pattern: create replacement table, copy data, drop
original, rename.

Revision ID: 003
Revises: 002
"""

import logging

from alembic import op
from sqlalchemy import text

LOGGER = logging.getLogger(__name__)

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Atomicity provided by Alembic's outer transaction (see migration 002 comment).

    # Drop views that SELECT * from scheduled_jobs before renaming/dropping the
    # underlying table (SQLite leaves dangling view references otherwise).
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

    # Create the replacement table with the new schema.
    # Note: "group" is double-quoted because GROUP is a SQLite reserved keyword.
    op.execute("""
        CREATE TABLE scheduled_jobs_003 (
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
            "group"               TEXT,
            cancelled_at          REAL,
            CHECK (app_key != '__hassette__' OR source_tier = 'framework')
        )
    """)

    # Copy all existing rows; backfill new columns with NULL (their natural default).
    op.execute("""
        INSERT INTO scheduled_jobs_003 (
            id, app_key, instance_index, job_name, handler_method,
            trigger_type,
            trigger_label, trigger_detail,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier,
            "group", cancelled_at
        )
        SELECT
            id, app_key, instance_index, job_name, handler_method,
            trigger_type,
            trigger_label, trigger_detail,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier,
            NULL AS "group", NULL AS cancelled_at
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_003 RENAME TO scheduled_jobs")

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
    # Warn about data loss: group and cancelled_at cannot be recovered after downgrade.
    conn = op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM scheduled_jobs"))
    row_count = result.scalar() or 0
    LOGGER.warning(
        "Downgrade 003→002: %d rows will permanently lose group/cancelled_at data",
        row_count,
    )

    # Atomicity provided by Alembic's outer transaction (see upgrade() comment).

    # Drop views first (same reason as in upgrade).
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

    # Recreate schema matching 002 final state (without group/cancelled_at).
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

    # Copy rows back; drop "group" and cancelled_at.
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
            trigger_label, trigger_detail,
            repeat, args_json, kwargs_json,
            source_location, registration_source, retired_at, source_tier
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_002 RENAME TO scheduled_jobs")

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

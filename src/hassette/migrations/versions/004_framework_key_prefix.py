"""Framework key prefix: update CHECK constraints to use GLOB for prefix matching.

Replaces the exact-match CHECK constraint on ``listeners`` and ``scheduled_jobs``:

    CHECK (app_key != '__hassette__' OR source_tier = 'framework')

with a GLOB-based prefix constraint that covers both the bare legacy key and any
component-specific key using the ``__hassette__.`` prefix:

    CHECK (app_key NOT GLOB '__hassette__*' OR source_tier = 'framework')

SQLite LIKE uses ``_`` as a single-character wildcard, which would incorrectly
match keys like ``__hassette_x__``. GLOB uses ``*`` and ``?`` instead, making
it safe for this pattern (``_`` is a literal in GLOB).

SQLite cannot modify CHECK constraints via ALTER TABLE, so this migration uses
the table-recreation pattern (same as migrations 002 and 003).

Revision ID: 004
Revises: 003
"""

import logging

from alembic import op
from sqlalchemy import text

LOGGER = logging.getLogger(__name__)

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Atomicity provided by Alembic's outer transaction (see migration 002 comment).

    # -------------------------------------------------------------------------
    # listeners
    # -------------------------------------------------------------------------

    # Drop views that SELECT * from listeners before renaming/dropping.
    op.execute("DROP VIEW IF EXISTS active_listeners")
    op.execute("DROP VIEW IF EXISTS active_framework_listeners")
    op.execute("DROP VIEW IF EXISTS active_app_listeners")

    # Create the replacement table with the updated CHECK constraint.
    op.execute("""
        CREATE TABLE listeners_004 (
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
            CHECK (app_key NOT GLOB '__hassette__*' OR source_tier = 'framework')
        )
    """)

    # Copy all existing rows.
    op.execute("""
        INSERT INTO listeners_004 (
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
    op.execute("ALTER TABLE listeners_004 RENAME TO listeners")

    # Recreate indexes (they were dropped with the original table).
    op.execute("CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_listeners_natural
            ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
            WHERE once = 0
    """)

    # Recreate views.
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

    # -------------------------------------------------------------------------
    # scheduled_jobs
    # -------------------------------------------------------------------------

    # Drop views that SELECT * from scheduled_jobs before renaming/dropping.
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

    # Create the replacement table with the updated CHECK constraint.
    # Note: "group" is double-quoted because GROUP is a SQLite reserved keyword.
    op.execute("""
        CREATE TABLE scheduled_jobs_004 (
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
            CHECK (app_key NOT GLOB '__hassette__*' OR source_tier = 'framework')
        )
    """)

    # Copy all existing rows.
    op.execute("""
        INSERT INTO scheduled_jobs_004 (
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
            "group", cancelled_at
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_004 RENAME TO scheduled_jobs")

    # Recreate indexes (they were dropped with the original table).
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


def downgrade() -> None:
    # Warn about constraint change: rows using prefixed framework keys may not
    # satisfy the old exact-match constraint after downgrade.
    conn = op.get_bind()
    result = conn.execute(text("SELECT COUNT(*) FROM listeners WHERE app_key GLOB '__hassette__.*'"))
    prefixed_listener_count = result.scalar() or 0
    result = conn.execute(text("SELECT COUNT(*) FROM scheduled_jobs WHERE app_key GLOB '__hassette__.*'"))
    prefixed_job_count = result.scalar() or 0
    if prefixed_listener_count > 0 or prefixed_job_count > 0:
        LOGGER.warning(
            "Downgrade 004→003: %d listener rows and %d scheduled_job rows use prefixed framework "
            "keys ('__hassette__.*') that will violate the old exact-match CHECK constraint. "
            "Those rows will be deleted before the downgrade to preserve referential integrity.",
            prefixed_listener_count,
            prefixed_job_count,
        )
        op.execute("DELETE FROM listeners WHERE app_key GLOB '__hassette__.*'")
        op.execute("DELETE FROM scheduled_jobs WHERE app_key GLOB '__hassette__.*'")

    # -------------------------------------------------------------------------
    # listeners — revert to 003 schema (exact-match CHECK)
    # -------------------------------------------------------------------------

    op.execute("DROP VIEW IF EXISTS active_listeners")
    op.execute("DROP VIEW IF EXISTS active_framework_listeners")
    op.execute("DROP VIEW IF EXISTS active_app_listeners")

    op.execute("""
        CREATE TABLE listeners_003 (
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
            CHECK (app_key != '__hassette__' OR source_tier = 'framework')
        )
    """)

    op.execute("""
        INSERT INTO listeners_003 (
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
    op.execute("ALTER TABLE listeners_003 RENAME TO listeners")

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

    # -------------------------------------------------------------------------
    # scheduled_jobs — revert to 003 schema (exact-match CHECK)
    # -------------------------------------------------------------------------

    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_framework_scheduled_jobs")
    op.execute("DROP VIEW IF EXISTS active_app_scheduled_jobs")

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
            "group", cancelled_at
        FROM scheduled_jobs
    """)

    op.execute("DROP TABLE scheduled_jobs")
    op.execute("ALTER TABLE scheduled_jobs_003 RENAME TO scheduled_jobs")

    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")
    op.execute("""
        CREATE UNIQUE INDEX idx_scheduled_jobs_natural
            ON scheduled_jobs(app_key, instance_index, job_name)
    """)

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

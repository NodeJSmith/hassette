"""Add name/retired_at columns, unique indexes, and active views for upsert-based registration.

Adds:
- ``name TEXT`` column to ``listeners`` (nullable, for the optional escape hatch)
- ``retired_at REAL`` column to both ``listeners`` and ``scheduled_jobs`` (nullable)
- Partial unique expression index ``idx_listeners_natural`` on ``listeners`` (WHERE once = 0)
- Unique index ``idx_scheduled_jobs_natural`` on ``scheduled_jobs``
- Database views ``active_listeners`` and ``active_scheduled_jobs``
- Covering index ``idx_hi_listener_id`` on ``handler_invocations(listener_id)``

Child tables (handler_invocations, job_executions) are rebuilt after the parent table
renames to restore correct FK references — this is required because SQLite silently
rewires FK references when a parent table is renamed (migration 004 pattern).

Revision ID: 006
Revises: 005
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ADD columns with arbitrary constraints in-place, and we need
    # expression-based UNIQUE indexes (not supported as table constraints).
    # Rebuild both parent tables with the new schema, then rebuild child tables
    # to fix FK references (same pattern as migration 004).

    # --- Step 1: Rebuild parent tables ---

    # listeners — add name TEXT and retired_at REAL
    op.execute("ALTER TABLE listeners RENAME TO _listeners_old")
    op.execute("""
        CREATE TABLE listeners (
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
            retired_at            REAL
        )
    """)
    op.execute("""
        INSERT INTO listeners (
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source
        )
        SELECT
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source
        FROM _listeners_old
    """)
    op.execute("DROP TABLE _listeners_old")

    # scheduled_jobs — add retired_at REAL
    op.execute("ALTER TABLE scheduled_jobs RENAME TO _scheduled_jobs_old")
    op.execute("""
        CREATE TABLE scheduled_jobs (
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
            retired_at            REAL
        )
    """)
    op.execute("""
        INSERT INTO scheduled_jobs (
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, trigger_value, repeat,
            args_json, kwargs_json,
            source_location, registration_source
        )
        SELECT
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, trigger_value, repeat,
            args_json, kwargs_json,
            source_location, registration_source
        FROM _scheduled_jobs_old
    """)
    op.execute("DROP TABLE _scheduled_jobs_old")

    # Recreate existing performance indexes from migration 004 (dropped when tables were rebuilt)
    op.execute("CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index)")
    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")

    # New unique indexes for upsert conflict targets
    op.execute("""
        CREATE UNIQUE INDEX idx_listeners_natural
            ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
            WHERE once = 0
    """)
    op.execute("""
        CREATE UNIQUE INDEX idx_scheduled_jobs_natural
            ON scheduled_jobs(app_key, instance_index, job_name)
    """)

    # --- Step 2: Rebuild child tables to fix corrupted FK references ---
    # After the parent table renames above, handler_invocations.listener_id
    # now references _listeners_old (which was dropped). Rebuild both child
    # tables so their FKs point to the new `listeners` and `scheduled_jobs`.

    # handler_invocations
    op.execute("ALTER TABLE handler_invocations RENAME TO _handler_invocations_old")
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO handler_invocations (
            id, listener_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        )
        SELECT
            id, listener_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        FROM _handler_invocations_old
    """)
    op.execute("DROP TABLE _handler_invocations_old")

    # Recreate existing indexes from migration 004
    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    # job_executions
    op.execute("ALTER TABLE job_executions RENAME TO _job_executions_old")
    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO job_executions (
            id, job_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        )
        SELECT
            id, job_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        FROM _job_executions_old
    """)
    op.execute("DROP TABLE _job_executions_old")

    # Recreate existing indexes from migration 004
    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")

    # --- Step 3: Create database views for active registration queries ---

    op.execute("""
        CREATE VIEW active_listeners AS
            SELECT * FROM listeners WHERE retired_at IS NULL
    """)
    op.execute("""
        CREATE VIEW active_scheduled_jobs AS
            SELECT * FROM scheduled_jobs WHERE retired_at IS NULL
    """)


def downgrade() -> None:
    # Reverse: drop views, drop new indexes, rebuild tables without new columns,
    # restore original indexes, rebuild child tables to fix FK references.

    # Drop views first (depend on the tables)
    op.execute("DROP VIEW IF EXISTS active_listeners")
    op.execute("DROP VIEW IF EXISTS active_scheduled_jobs")

    # --- Rebuild listeners without name and retired_at ---
    op.execute("ALTER TABLE listeners RENAME TO _listeners_old")
    op.execute("""
        CREATE TABLE listeners (
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
            registration_source   TEXT
        )
    """)
    op.execute("""
        INSERT INTO listeners (
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source
        )
        SELECT
            id, app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            predicate_description, human_description,
            source_location, registration_source
        FROM _listeners_old
    """)
    op.execute("DROP TABLE _listeners_old")

    # --- Rebuild scheduled_jobs without retired_at ---
    op.execute("ALTER TABLE scheduled_jobs RENAME TO _scheduled_jobs_old")
    op.execute("""
        CREATE TABLE scheduled_jobs (
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
            registration_source   TEXT
        )
    """)
    op.execute("""
        INSERT INTO scheduled_jobs (
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, trigger_value, repeat,
            args_json, kwargs_json,
            source_location, registration_source
        )
        SELECT
            id, app_key, instance_index, job_name, handler_method,
            trigger_type, trigger_value, repeat,
            args_json, kwargs_json,
            source_location, registration_source
        FROM _scheduled_jobs_old
    """)
    op.execute("DROP TABLE _scheduled_jobs_old")

    # Restore migration 004 indexes
    op.execute("CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index)")
    op.execute("CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index)")

    # Rebuild child tables to fix FK references
    op.execute("ALTER TABLE handler_invocations RENAME TO _handler_invocations_old")
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO handler_invocations (
            id, listener_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        )
        SELECT
            id, listener_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        FROM _handler_invocations_old
    """)
    op.execute("DROP TABLE _handler_invocations_old")

    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    op.execute("ALTER TABLE job_executions RENAME TO _job_executions_old")
    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts    REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)
    op.execute("""
        INSERT INTO job_executions (
            id, job_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        )
        SELECT
            id, job_id, session_id, execution_start_ts,
            duration_ms, status, error_type, error_message, error_traceback
        FROM _job_executions_old
    """)
    op.execute("DROP TABLE _job_executions_old")

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")

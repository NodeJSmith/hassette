"""Drop dead upsert columns and UNIQUE constraints from registration tables.

The upsert pattern (ON CONFLICT ... DO UPDATE SET last_registered_at) was dead
code: clear_registrations() deletes all rows before re-registration, so the
ON CONFLICT path never fires. The first_registered_at and last_registered_at
columns are write-only — nothing SELECTs them. The UNIQUE constraints served
only the upsert and prevented registering two listeners with the same handler
and topic but different predicates.

Revision ID: 004
Revises: 003
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot DROP columns or constraints in-place.
    # Rebuild both parent tables without the dead columns and UNIQUE constraints.
    #
    # IMPORTANT: SQLite 3.26+ always rewrites FK references in child tables
    # when a parent table is renamed (PRAGMA foreign_keys has no effect on this).
    # After renaming `listeners` → `_listeners_old`, the FK in handler_invocations
    # silently changes to reference `_listeners_old`. We must rebuild the child
    # tables after the parent tables to restore correct FK references.

    # --- Step 1: Rebuild parent tables ---

    # listeners
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

    # scheduled_jobs
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

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")


def downgrade() -> None:
    # Restore first_registered_at, last_registered_at, and UNIQUE constraints.
    # WARNING: If duplicate rows exist (same natural key, different predicates),
    # the INSERT will fail due to the restored UNIQUE constraint. Clear the
    # listeners/scheduled_jobs tables before downgrading if duplicates exist.

    # --- listeners ---
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
            first_registered_at   REAL    NOT NULL DEFAULT 0.0,
            last_registered_at    REAL    NOT NULL DEFAULT 0.0,
            UNIQUE (app_key, instance_index, handler_method, topic)
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

    # --- scheduled_jobs ---
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
            first_registered_at   REAL    NOT NULL DEFAULT 0.0,
            last_registered_at    REAL    NOT NULL DEFAULT 0.0,
            UNIQUE (app_key, instance_index, job_name)
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

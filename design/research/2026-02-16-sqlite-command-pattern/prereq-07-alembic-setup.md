# Prereq 7: Alembic Setup + Migration Directory Layout

**Status**: Decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — initial migration creates the tables defined there
- [Prereq 6: Open questions](./prereq-06-open-questions.md) — DB file location, aiosqlite decision

## Dependents

- **None** — this is the last prereq before implementation begins

## Problem

The project has no migration tooling. The new SQLite database needs schema versioning from day one so future schema changes (new tables, column additions, index changes) can be applied to existing installations without data loss.

## Decisions

### Alembic with raw SQL (no SQLAlchemy)

Alembic supports autogeneration (requires SQLAlchemy models) and raw SQL (hand-written `op.execute()`). **Raw SQL**. The project doesn't use SQLAlchemy and adding an ORM for migration autogeneration isn't justified. Raw SQL migrations are explicit, auditable, and avoid a large transitive dependency.

### Migrations inside the package

```
src/hassette/
├── migrations/
│   ├── env.py          # Alembic environment config
│   ├── script.py.mako  # Migration template
│   └── versions/
│       └── 001_initial_schema.py
└── ...
```

Migrations ship with the package. `DatabaseService` locates them via `Path(__file__).parent / "migrations"`. Works for both development and installed packages. `alembic.ini` lives at the project root for development convenience (`alembic revision`, `alembic upgrade`), but `DatabaseService` configures Alembic programmatically at runtime.

### Core dependencies (not optional)

```toml
# pyproject.toml
dependencies = [
    # ... existing deps ...
    "aiosqlite>=0.20",
    "alembic>=1.13",
]
```

The DB is a framework feature, not a plugin. Optional dependencies add complexity to installation instructions for minimal savings.

## Programmatic Alembic config

`DatabaseService` doesn't use `alembic.ini` at runtime — it configures Alembic programmatically:

```python
from alembic.config import Config
from alembic import command

def _run_migrations(self, db_path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
```

## Initial migration: `001_initial_schema`

Creates all five tables + indexes from [prereq 5](./prereq-05-schema-design.md):

```python
"""Initial schema: sessions, listeners, scheduled_jobs, handler_invocations, job_executions."""

revision = "001"
down_revision = None

from alembic import op

def upgrade():
    # Sessions
    op.execute("""
        CREATE TABLE sessions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at            REAL    NOT NULL,
            stopped_at            REAL,
            last_heartbeat_at     REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)

    # Parent tables
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
            source_location       TEXT    NOT NULL,
            registration_source   TEXT,
            first_registered_at   REAL    NOT NULL,
            last_registered_at    REAL    NOT NULL,
            UNIQUE (app_key, instance_index, handler_method, topic)
        )
    """)

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
            first_registered_at   REAL    NOT NULL,
            last_registered_at    REAL    NOT NULL,
            UNIQUE (app_key, instance_index, job_name)
        )
    """)

    # Execution tables
    op.execute("""
        CREATE TABLE handler_invocations (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            listener_id           INTEGER NOT NULL REFERENCES listeners(id),
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts  REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)

    op.execute("""
        CREATE TABLE job_executions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id                INTEGER NOT NULL REFERENCES scheduled_jobs(id),
            session_id            INTEGER NOT NULL REFERENCES sessions(id),
            execution_start_ts  REAL    NOT NULL,
            duration_ms           REAL    NOT NULL,
            status                TEXT    NOT NULL,
            error_type            TEXT,
            error_message         TEXT,
            error_traceback       TEXT
        )
    """)

    # Indexes
    op.execute("CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts)")
    op.execute("CREATE INDEX idx_hi_session ON handler_invocations(session_id)")

    op.execute("CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC)")
    op.execute("CREATE INDEX idx_je_time ON job_executions(execution_start_ts)")
    op.execute("CREATE INDEX idx_je_session ON job_executions(session_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS job_executions")
    op.execute("DROP TABLE IF EXISTS handler_invocations")
    op.execute("DROP TABLE IF EXISTS scheduled_jobs")
    op.execute("DROP TABLE IF EXISTS listeners")
    op.execute("DROP TABLE IF EXISTS sessions")
```

Note: Downgrade drops in reverse dependency order (execution tables before parent tables) to respect FK constraints.

## Integration with `DatabaseService`

`DatabaseService.on_initialize()` flow:

1. Resolve DB path from config (`hassette.config.db_path` or default `data_dir / "hassette.db"`)
2. Run Alembic migrations to HEAD (creates DB file if missing, applies pending migrations if exists)
3. Set PRAGMAs (WAL mode, synchronous, busy_timeout, foreign_keys)
4. Open the `aiosqlite` connection
5. Mark orphaned sessions as `"unknown"` (`UPDATE sessions SET status = 'unknown', stopped_at = last_heartbeat_at WHERE status = 'running'`)
6. Insert new session row with `status = 'running'`
7. `mark_ready()`

## Scope

1. Add `aiosqlite` and `alembic` to `pyproject.toml` (core dependencies)
2. Create `src/hassette/migrations/` directory with `env.py`, `script.py.mako`
3. Create `alembic.ini` at project root (development convenience)
4. Write `001_initial_schema.py` migration
5. Test: migration creates tables on fresh DB, is idempotent on existing DB

## Deliverable

Working Alembic setup that can create the initial schema. This is the last infrastructure prereq — once done, the `DatabaseService` and `CommandExecutor` implementation can begin.

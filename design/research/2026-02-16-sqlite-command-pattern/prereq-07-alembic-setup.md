# Prereq 7: Alembic Setup + Migration Directory Layout

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — initial migration creates the tables defined there
- [Prereq 6: Open questions](./prereq-06-open-questions.md) — DB file location affects Alembic config

## Dependents

- **None** — this is the last prereq before implementation begins

## Problem

The project has no migration tooling. The new SQLite database needs schema versioning from day one so future schema changes (new tables, column additions, index changes) can be applied to existing installations without data loss.

## Approach: Alembic with raw SQL

Alembic is the standard Python migration tool. It supports two modes:

1. **Autogenerate** — compares SQLAlchemy models to DB schema, generates migrations. Requires SQLAlchemy models.
2. **Raw SQL** — hand-written `op.execute("CREATE TABLE ...")` in upgrade/downgrade functions. No SQLAlchemy dependency.

**Choice**: Raw SQL. The project doesn't use SQLAlchemy and adding an ORM for migration autogeneration isn't justified. Raw SQL migrations are explicit, auditable, and avoid a large transitive dependency.

## Directory layout

Two options:

### Option A: Inside the package (recommended)

```
src/hassette/
├── migrations/
│   ├── env.py          # Alembic environment config
│   ├── script.py.mako  # Migration template
│   └── versions/
│       └── 001_initial_schema.py
├── alembic.ini         # ? or at project root
└── ...
```

**Pros**: Migrations ship with the package. `DatabaseService` can locate them via `importlib.resources` or `Path(__file__).parent / "migrations"`. Works for both development and installed packages.

**Cons**: Slightly unconventional (Alembic usually lives at project root).

### Option B: Project root

```
hassette/
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── src/hassette/
│   └── ...
└── ...
```

**Pros**: Standard Alembic layout. `alembic` CLI works from project root without path tricks.

**Cons**: Migrations don't ship with the package. A user installing hassette as a library wouldn't get the migrations. `DatabaseService` would need to handle "no migrations found" for installed packages.

**Recommendation**: Option A. Hassette is a framework that manages its own DB lifecycle — migrations must be available at runtime, not just at development time. `DatabaseService.on_initialize()` runs migrations on startup, so they must be importable from the installed package.

## `alembic.ini` placement

Keep `alembic.ini` at the project root for development convenience (`alembic revision`, `alembic upgrade`), but `DatabaseService` doesn't use it — it configures Alembic programmatically:

```python
from alembic.config import Config
from alembic import command

def _run_migrations(self, db_path: Path) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
```

This pattern (programmatic Alembic config) is well-documented and avoids runtime dependency on `alembic.ini` file location.

## Initial migration: `001_initial_schema`

The first migration creates all three tables + indexes from [prereq 5](./prereq-05-schema-design.md):

```python
"""Initial schema: handler_invocations, job_executions, sessions."""

revision = "001"
down_revision = None

from alembic import op

def upgrade():
    op.execute("""
        CREATE TABLE handler_invocations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stable_key  TEXT    NOT NULL,
            owner       TEXT    NOT NULL,
            topic       TEXT    NOT NULL,
            handler_name TEXT   NOT NULL,
            started_at  REAL    NOT NULL,
            duration_ms REAL    NOT NULL,
            status      TEXT    NOT NULL,
            error_type  TEXT,
            error_message TEXT,
            error_traceback TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # ... indexes, job_executions, sessions (from prereq 5)

def downgrade():
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS job_executions")
    op.execute("DROP TABLE IF EXISTS handler_invocations")
```

## New dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
db = ["aiosqlite>=0.20", "alembic>=1.13"]
```

Or as core dependencies if the DB is always available (even if `run_db=False` skips initialization). The overhead of having them installed but unused is negligible.

**Recommendation**: Core dependencies (not optional). The DB is a framework feature, not a plugin. Optional dependencies add complexity to installation instructions for minimal savings.

## Integration with `DatabaseService`

`DatabaseService.on_initialize()` flow:

1. Resolve DB path from config (`hassette.config.db_path` or default `data_dir / "hassette.db"`)
2. Run Alembic migrations to HEAD (creates DB file if missing, applies pending migrations if exists)
3. Set PRAGMAs (WAL mode, synchronous, busy_timeout)
4. Open the `aiosqlite` connection
5. `mark_ready()`

This means the first startup creates the DB from scratch via the migration, and subsequent startups apply any new migrations added in framework updates.

## Scope

1. Add `aiosqlite` and `alembic` to `pyproject.toml`
2. Create `src/hassette/migrations/` directory with `env.py`, `script.py.mako`
3. Create `alembic.ini` at project root (development convenience)
4. Write `001_initial_schema.py` migration
5. Test: migration creates tables on fresh DB, is idempotent on existing DB

## Deliverable

Working Alembic setup that can create the initial schema. This is the last prereq — once done, the `DatabaseService` and `CommandExecutor` implementation can begin.

"""Integration tests for DatabaseService — Alembic migration chain and schema correctness."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "hassette" / "migrations"

# Hardcoded because this project uses raw Alembic operations (op.create_table, op.add_column),
# not autogenerate from ORM models — there is no Base.metadata to compare against.
# Update this dict when adding new migrations.
EXPECTED_TABLES = {
    "sessions": {
        "id",
        "started_at",
        "stopped_at",
        "last_heartbeat_at",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
        "dropped_overflow",
        "dropped_exhausted",
        "dropped_no_session",
        "dropped_shutdown",
    },
    "listeners": {
        "id",
        "app_key",
        "instance_index",
        "handler_method",
        "topic",
        "debounce",
        "throttle",
        "once",
        "priority",
        "predicate_description",
        "source_location",
        "registration_source",
        "human_description",
        "name",
        "retired_at",
        "source_tier",
        "immediate",
        "duration",
        "entity_id",
    },
    "scheduled_jobs": {
        "id",
        "app_key",
        "instance_index",
        "job_name",
        "handler_method",
        "trigger_type",
        "trigger_label",
        "trigger_detail",
        "repeat",
        "args_json",
        "kwargs_json",
        "source_location",
        "registration_source",
        "retired_at",
        "source_tier",
        "group",
        "cancelled_at",
        "name_auto",
    },
    "handler_invocations": {
        "id",
        "listener_id",
        "session_id",
        "execution_start_ts",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
        "execution_id",
        "is_di_failure",
        "source_tier",
        "trigger_context_id",
        "trigger_origin",
    },
    "job_executions": {
        "id",
        "job_id",
        "session_id",
        "execution_start_ts",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
        "execution_id",
        "is_di_failure",
        "source_tier",
    },
    "log_records": {
        "id",
        "seq",
        "timestamp",
        "level",
        "logger_name",
        "func_name",
        "lineno",
        "message",
        "exc_info",
        "app_key",
        "instance_name",
        "instance_index",
        "execution_id",
        "source_tier",
    },
}


def _make_alembic_config(db_path: Path):
    """Build a programmatic Alembic Config matching production (DatabaseService._run_migrations)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def test_migration_chain_has_no_gaps(tmp_path: Path) -> None:
    """Walk the revision chain from base to heads and verify no gaps or dangling down_revision refs."""
    config = _make_alembic_config(tmp_path / "unused.db")
    script = ScriptDirectory.from_config(config)

    revisions = list(script.walk_revisions())
    assert len(revisions) >= 1, f"Expected at least 1 revision, got {len(revisions)}"

    # Build a set of all known revision IDs
    revision_ids = {rev.revision for rev in revisions}

    for rev in revisions:
        if rev.down_revision is not None:
            # down_revision can be a string or a tuple (for merge migrations)
            down_revs = rev.down_revision if isinstance(rev.down_revision, tuple) else (rev.down_revision,)
            for dr in down_revs:
                assert dr in revision_ids, (
                    f"Revision {rev.revision} references down_revision {dr!r} "
                    f"which does not exist in the script directory"
                )

    # Verify exactly one head (no branch forks)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 head, got {len(heads)}: {heads}"

    # Verify exactly one base
    bases = script.get_bases()
    assert len(bases) == 1, f"Expected exactly 1 base, got {len(bases)}: {bases}"


def test_fresh_db_migrates_to_head(tmp_path: Path) -> None:
    """Create an empty SQLite DB, run 'upgrade head', and verify all expected tables exist."""
    db_path = tmp_path / "test.db"
    config = _make_alembic_config(db_path)
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        assert tables == sorted(EXPECTED_TABLES.keys())
    finally:
        conn.close()


def test_sequential_upgrade_from_each_revision(tmp_path: Path) -> None:
    """For each revision, stamp a fresh DB at that revision, then upgrade to head."""
    config = _make_alembic_config(tmp_path / "script_dir.db")
    script = ScriptDirectory.from_config(config)

    # Collect revisions in base-to-head order (walk_revisions yields head-first)
    revisions = list(script.walk_revisions())
    revisions.reverse()

    for i, rev in enumerate(revisions):
        db_path = tmp_path / f"test_{i}_{rev.revision}.db"
        rev_config = _make_alembic_config(db_path)

        # Run migrations up to this revision to create the schema at that point
        command.upgrade(rev_config, rev.revision)

        # Then upgrade from this revision to head
        command.upgrade(rev_config, "head")

        # Verify the DB is at head and has all tables
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
            )
            tables = sorted(row[0] for row in cursor.fetchall())
            assert tables == sorted(EXPECTED_TABLES.keys()), (
                f"After upgrading from {rev.revision} to head, "
                f"expected tables {sorted(EXPECTED_TABLES.keys())} but got {tables}"
            )
        finally:
            conn.close()


def test_migration_schema_matches_expected_columns(tmp_path: Path) -> None:
    """After running all migrations, compare the resulting columns against the expected schema."""
    db_path = tmp_path / "test.db"
    config = _make_alembic_config(db_path)
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    try:
        # Get all user tables
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}

        expected_table_names = set(EXPECTED_TABLES.keys())

        # Check for tables in expected but missing from migrations
        missing_tables = expected_table_names - actual_tables
        assert not missing_tables, f"Tables defined in expected schema but missing from DB: {missing_tables}"

        # Check for tables in migrations but not in expected schema
        extra_tables = actual_tables - expected_table_names
        assert not extra_tables, f"Tables in DB but missing from expected schema: {extra_tables}"

        # Compare columns for each table
        for table_name in sorted(actual_tables):
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            actual_columns = {row[1] for row in cursor.fetchall()}
            expected_columns = EXPECTED_TABLES[table_name]

            missing_columns = expected_columns - actual_columns
            assert not missing_columns, (
                f"Table {table_name!r}: columns in expected schema but missing from DB: {missing_columns}"
            )

            extra_columns = actual_columns - expected_columns
            assert not extra_columns, (
                f"Table {table_name!r}: columns in DB but missing from expected schema: {extra_columns}"
            )
    finally:
        conn.close()


def test_auto_vacuum_migration(tmp_path: Path) -> None:
    """DatabaseService._run_migrations() sets auto_vacuum = INCREMENTAL before Alembic runs."""
    db_path = tmp_path / "test.db"

    # Simulate what DatabaseService._run_migrations() does: set auto_vacuum before Alembic
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
    finally:
        conn.close()

    # Run migrations to head
    config = _make_alembic_config(db_path)
    command.upgrade(config, "head")

    # Verify auto_vacuum is INCREMENTAL (2)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("PRAGMA auto_vacuum")
        mode_after = cursor.fetchone()[0]
        assert mode_after == 2, f"Expected auto_vacuum = 2 after migration, got {mode_after}"
    finally:
        conn.close()

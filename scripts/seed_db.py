#!/usr/bin/env python3
"""Generate deterministic seed SQLite databases for hassette telemetry scenarios.

Creates a fresh SQLite database (schema applied via the real migration runner)
and populates it with hand-authored, fully deterministic data for a named
scenario. Useful for frontend QA, CLI doc generation, visual regression
screenshots, and demos that need the monitoring dashboard in a specific state
without waiting on a live Home Assistant instance.

Usage::

    python scripts/seed_db.py --scenario healthy
    python scripts/seed_db.py --scenario degraded --output /tmp/hassette-degraded.db

The scenario generators themselves live in ``scripts/seed_scenarios/`` -- one module per
scenario, plus a shared ``base`` module holding ``SeedContext`` and the seed helpers. This
file owns only the CLI, the transaction/atomic-swap machinery, and the post-seed integrity
checks.
"""

import argparse
import sqlite3
from pathlib import Path

from seed_scenarios import SCENARIOS, SeedContext, SeedIntegrityError

from hassette.core.migration_runner import run_migrations

_SUMMARY_TABLES = ("sessions", "listeners", "scheduled_jobs", "executions", "log_records", "blocking_events")

_DANGLING_EXECUTION_ID_QUERY = """
    SELECT t.execution_id
    FROM {table} t
    LEFT JOIN executions e ON t.execution_id = e.execution_id
    WHERE t.execution_id IS NOT NULL AND e.execution_id IS NULL
"""


def _remove_sqlite_files(db_path: Path) -> None:
    """Remove a SQLite main file and its -wal/-shm siblings, if present."""
    db_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _assert_foreign_keys_clean(conn: sqlite3.Connection) -> None:
    """Run PRAGMA foreign_key_check and abort with details on any violation."""
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        details = "\n".join(f"  table={row[0]} rowid={row[1]} parent={row[2]} fkid={row[3]}" for row in violations)
        raise SeedIntegrityError(f"Foreign key violations detected:\n{details}")


def _assert_no_dangling_execution_ids(conn: sqlite3.Connection, table: str) -> None:
    """Abort if ``table`` has non-null execution_id values with no matching executions row.

    ``table`` is always one of our own two literal call sites ("log_records",
    "blocking_events") — never user input.
    """
    sql = _DANGLING_EXECUTION_ID_QUERY.format(table=table)
    rows = conn.execute(sql).fetchall()
    if rows:
        ids = ", ".join(row[0] for row in rows)
        raise SeedIntegrityError(f"{table} has execution_id value(s) with no matching executions row: {ids}")


def _collect_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for all 6 telemetry tables plus a distinct-app-key count."""
    summary = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 — table is a static literal
        for table in _SUMMARY_TABLES
    }
    apps_row = conn.execute(
        "SELECT COUNT(*) FROM (SELECT app_key FROM listeners UNION SELECT app_key FROM scheduled_jobs)"
    ).fetchone()
    summary["apps"] = apps_row[0]
    return summary


def generate_scenario(scenario: str, output_path: Path, tmp_path: Path) -> dict[str, int]:
    """Generate one scenario to ``tmp_path`` and atomically swap it into ``output_path``.

    Applies migrations, runs the scenario generator inside a single BEGIN IMMEDIATE /
    COMMIT transaction, verifies referential integrity, then swaps the file into place.
    On any failure, the temp file is removed and the exception propagates — the
    destination path is left untouched.
    """
    _remove_sqlite_files(tmp_path)

    try:
        run_migrations(tmp_path)

        conn = sqlite3.connect(tmp_path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            ctx = SeedContext(cursor=cursor)

            try:
                cursor.execute("BEGIN IMMEDIATE")
                SCENARIOS[scenario](ctx)
            except Exception:
                conn.rollback()
                raise
            conn.commit()

            _assert_foreign_keys_clean(conn)
            _assert_no_dangling_execution_ids(conn, "log_records")
            _assert_no_dangling_execution_ids(conn, "blocking_events")

            summary = _collect_summary(conn)
        finally:
            conn.close()

        for suffix in ("-wal", "-shm"):
            Path(f"{output_path}{suffix}").unlink(missing_ok=True)
        tmp_path.replace(output_path)
    except Exception:
        _remove_sqlite_files(tmp_path)
        raise

    return summary


def _print_summary(scenario: str, output_path: Path, summary: dict[str, int]) -> None:
    print(f"Seeded scenario '{scenario}' -> {output_path}")
    print(f"  apps:            {summary['apps']}")
    print(f"  listeners:       {summary['listeners']}")
    print(f"  scheduled_jobs:  {summary['scheduled_jobs']}")
    print(f"  executions:      {summary['executions']}")
    print(f"  log_records:     {summary['log_records']}")
    print(f"  blocking_events: {summary['blocking_events']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic seed SQLite database for a named hassette telemetry scenario."
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS),
        help="Which scenario to generate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output SQLite file path (default: ./hassette-{scenario}.db)",
    )
    args = parser.parse_args()

    output_path: Path = (args.output or Path(f"hassette-{args.scenario}.db")).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".tmp")

    try:
        summary = generate_scenario(args.scenario, output_path, tmp_path)
    except SeedIntegrityError as exc:
        raise SystemExit(f"Seed integrity check failed: {exc}") from exc
    except (sqlite3.OperationalError, RuntimeError) as exc:
        # A same-path collision most often surfaces during run_migrations(), which wraps any
        # sqlite3.Error (migration_runner.py) in a RuntimeError -- check the cause chain, not
        # just the raised type, and narrow to OperationalError specifically so an unrelated
        # migration bug still propagates with its real traceback instead of this friendlier
        # message.
        cause = exc if isinstance(exc, sqlite3.OperationalError) else exc.__cause__
        if not isinstance(cause, sqlite3.OperationalError):
            raise
        raise SystemExit(
            f"Database error while seeding {output_path}: {cause}\n"
            f"Another seed_db.py run may be writing to this path — wait for it to finish and retry."
        ) from exc

    _print_summary(args.scenario, output_path, summary)


if __name__ == "__main__":
    main()

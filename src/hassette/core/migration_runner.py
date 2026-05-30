"""PRAGMA user_version migration runner.

Replaces Alembic. Applies numbered .sql files from the migrations_sql/ directory
using SQLite's native PRAGMA user_version for version tracking. Each migration
runs inside BEGIN IMMEDIATE / COMMIT — crash-safe atomic application.
"""

import sqlite3
import warnings
from pathlib import Path

# Plain SQL files, not a Python package — located via __file__ path so they
# resolve in both editable and wheel installs. Intentionally no __init__.py.
_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations_sql"

# SQLite PRAGMA auto_vacuum mode value for INCREMENTAL.
_AUTO_VACUUM_INCREMENTAL = 2


def run_migrations(db_path: Path, *, target: int | None = None) -> None:
    """Apply pending migrations to the database at db_path (synchronous).

    Args:
        db_path: Filesystem path to the SQLite database file.
        target: Apply migrations up to this version. Defaults to the highest
            numbered .sql file found in migrations_sql/.
    """
    sql_files = _collect_migrations(target)
    if not sql_files:
        return

    max_target = max(sql_files)

    if target is None:
        target = max_target

    current = _read_user_version(db_path)

    if current == 0:
        _set_auto_vacuum(db_path)

    for version, sql_path in sorted(sql_files.items()):
        if version <= current or version > target:
            continue
        _apply_migration(db_path, version, sql_path)


def _collect_migrations(target: int | None) -> dict[int, Path]:
    """Return {version: path} for all .sql files in migrations_sql/."""
    result: dict[int, Path] = {}
    for path in _MIGRATIONS_DIR.glob("*.sql"):
        stem = path.stem  # e.g. "001"
        if stem.isdigit():
            version = int(stem)
            if target is None or version <= target:
                result[version] = path
    return result


def _read_user_version(db_path: Path) -> int:
    """Return PRAGMA user_version from the database (0 for fresh databases)."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _set_auto_vacuum(db_path: Path) -> None:
    """Set auto_vacuum = INCREMENTAL on a fresh database.

    Must use a raw connection with no active transaction — SQLite refuses to
    change auto_vacuum when pages already exist or inside a transaction.
    """
    conn = sqlite3.connect(db_path)
    try:
        current_mode = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if current_mode == _AUTO_VACUUM_INCREMENTAL:
            return
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        # SQLite silently ignores the change if pages already exist. Re-read to
        # confirm it took effect rather than running the DB in the wrong mode.
        applied = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if applied != _AUTO_VACUUM_INCREMENTAL:
            warnings.warn(
                f"auto_vacuum could not be set to INCREMENTAL (got {applied}); "
                "the database may have been opened before tables were created.",
                RuntimeWarning,
                stacklevel=2,
            )
    finally:
        conn.close()


def _apply_migration(db_path: Path, version: int, sql_path: Path) -> None:
    """Apply one migration file inside BEGIN IMMEDIATE / COMMIT.

    PRAGMA user_version = N is the last statement in the transaction so that
    a crash mid-migration leaves the version at the previous value.

    sqlite3.executescript() issues an implicit COMMIT before execution, which
    would end a BEGIN IMMEDIATE we opened before calling it. To work around this,
    the entire migration (BEGIN IMMEDIATE ... COMMIT) is assembled as a single
    script string and passed to executescript() so SQLite handles it atomically.
    """
    sql = sql_path.read_text(encoding="utf-8")
    script = f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;\n"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(script)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Migration {version} ({sql_path.name}) failed: {exc}") from exc
    finally:
        conn.close()

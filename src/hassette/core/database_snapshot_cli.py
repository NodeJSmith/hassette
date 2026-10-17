"""Command-line entry for the add-on's database snapshot and restore steps.

Run by the add-on's ``backup_pre.sh`` and ``run.sh`` (design/specs/129-ha-addon-v01/design.md, D10)::

    python -m hassette.core.database_snapshot_cli snapshot <db> <snapshot>
    python -m hassette.core.database_snapshot_cli restore <db> <snapshot>

A module of its own because ``python -m`` warns when the module it runs was already imported, and importing the
hassette package imports ``database_snapshot`` through ``DatabaseService``.
"""

import sqlite3
import sys
from pathlib import Path

from hassette.core.database_snapshot import restore_snapshot, write_snapshot

USAGE = "usage: python -m hassette.core.database_snapshot_cli snapshot|restore <db> <snapshot>"


def main(argv: list[str]) -> int:
    """Run ``snapshot`` or ``restore`` from the command line; print what happened and return the exit code."""
    if len(argv) != 3 or argv[0] not in ("snapshot", "restore"):
        print(USAGE, file=sys.stderr)
        return 2
    command, db_path, snapshot_path = argv[0], Path(argv[1]), Path(argv[2])

    if command == "restore":
        try:
            restored = restore_snapshot(db_path, snapshot_path)
        except OSError as exc:
            print(f"couldn't restore {db_path} from {snapshot_path}: {exc}", file=sys.stderr)
            return 1
        if restored:
            print(f"Restored the database from the backup snapshot {snapshot_path}")
        else:
            print("No database restore needed (the database exists, or there is no snapshot)")
        return 0

    try:
        written = write_snapshot(db_path, snapshot_path)
    except (sqlite3.Error, OSError) as exc:
        print(f"couldn't snapshot {db_path} to {snapshot_path}: {exc}", file=sys.stderr)
        return 1
    if written:
        print(f"Wrote the database snapshot {snapshot_path}")
    else:
        print(f"No database at {db_path} yet; nothing to snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

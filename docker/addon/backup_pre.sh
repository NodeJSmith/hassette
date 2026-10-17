#!/usr/bin/env bash
# The add-on's backup_pre hook (design/specs/129-ha-addon-v01/design.md, D10). Supervisor runs it with
# `docker exec` before a hot backup, and the backup excludes the live database files, so this writes the
# consistent single-file snapshot the backup carries instead. run.sh restores it at start after a restore.
#
# Supervisor runs it with the image's environment, not run.sh's exports, so the paths are literals.
# tests/unit/test_addon_image.py checks they match run.sh's HASSETTE__DATABASE__* pins.

# No -e: the failure branch below reports the error and exits itself.
set -uo pipefail

DB_PATH="/data/hassette.db"
SNAPSHOT_PATH="/data/backup/hassette-snapshot.db"
VENV_PYTHON="/app/.venv/bin/python"

if output=$("${VENV_PYTHON}" -m hassette.core.database_snapshot_cli snapshot "${DB_PATH}" "${SNAPSHOT_PATH}" 2>&1); then
    echo "${output}"
    exit 0
fi

# A non-zero exit leaves this add-on out of the backup, so the failure is visible on the backup instead of
# the backup silently carrying an older snapshot. Supervisor logs this script's output only at debug level,
# so the reason also goes to the add-on log (the container's stderr, which PID 1 holds). That write is
# best-effort: if /proc/1/fd/2 can't be opened, the shell's own error is discarded too.
message="ERROR: the backup can't include hassette's database: ${output}"
echo "${message}" >&2
echo "${message}" 2>/dev/null >/proc/1/fd/2
exit 1

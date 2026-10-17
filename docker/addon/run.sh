#!/usr/bin/env bash
# The Home Assistant add-on's entrypoint (design/specs/129-ha-addon-v01/design.md, D4). It seeds an empty
# config folder, pins the settings the add-on owns, restores the database after a backup restore, maps the
# add-on options, then hands off to the image's own docker_start.sh. Values hassette resolves itself (config
# locations, the token's contents) are never computed here.

set -euo pipefail

CONFIG_ROOT="/config"
SEED_DIR="/app/docker/addon/seed"
OPTIONS_FILE="/data/options.json"
VENV_PYTHON="/app/.venv/bin/python"
SUPERVISOR_URL="http://supervisor"
ISSUES_URL="https://github.com/NodeJSmith/hassette/issues"

# Usage: addon_halt <what failed> <remedy>
# docker_start.sh's halt doesn't run until the exec at the end, so this prints the same banner and exits at
# once, as halt does under the add-on.
addon_halt() {
    echo ""
    echo "─────────────────────────────────────────────────────────"
    echo "  HASSETTE CAN'T START: $1"
    echo ""
    echo "  $2"
    echo "─────────────────────────────────────────────────────────"
    exit 1
}

if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
    addon_halt "this image only works as a Home Assistant add-on (SUPERVISOR_TOKEN is not set)" \
        "To run hassette in plain Docker, use the ghcr.io/nodejsmith/hassette image instead"
fi

# Seed before anything else writes to /config (hassette's token file lands there too), and only into an
# empty folder, so a user's own files never sit beside the example (D10).
if [ -z "$(ls -A "${CONFIG_ROOT}")" ]; then
    echo "The config folder is empty; adding a starter hassette.toml and an example app"
    cp -R "${SEED_DIR}/." "${CONFIG_ROOT}/" \
        || addon_halt "couldn't write the starter files to ${CONFIG_ROOT}" \
            "Restart the add-on from its page; if that doesn't help, report it at ${ISSUES_URL}"
fi

# Add-on-owned settings, pinned on every start. The process environment outranks hassette.toml and
# /config/.env, so a file can't move hassette off what Supervisor and the integration expect (D6-D8, D10).
# docker_start.sh's own switches (HASSETTE_DOCKER_*) and uv's cache:
export HASSETTE_DOCKER_RUNTIME=addon
export HASSETTE_DOCKER_RETRY_DELAY=0
export HASSETTE_DOCKER_PRUNE_UV_CACHE=0
export UV_CACHE_DIR=/data/uv_cache
# hassette's settings (HASSETTE__*). tests/unit/test_addon_image.py reads the web_api lines, so keep each a
# literal single-line export. 172.30.32.2 is Supervisor's ingress gateway, and 8126 is the port config.yaml's
# ingress_port and the HEALTHCHECK use.
export HASSETTE__BASE_URL=http://supervisor/core
export HASSETTE__TOKEN="${SUPERVISOR_TOKEN}"
export HASSETTE__WEB_API__TRUSTED_PROXIES='["172.30.32.2"]'
export HASSETTE__WEB_API__HOST=0.0.0.0
export HASSETTE__WEB_API__PORT=8126
export HASSETTE__WEB_API__RUN=true
export HASSETTE__WEB_API__RUN_UI=true
export HASSETTE__WEB_API__AUTH_ENABLED=true
export HASSETTE__WEB_API__TOKEN_FILE=/config/.web_api_token
export HASSETTE__DATABASE__PATH=/data/hassette.db
export HASSETTE__DATABASE__SHUTDOWN_SNAPSHOT_PATH=/data/backup/hassette-snapshot.db

# Backups exclude the live database files and carry the snapshot backup_pre.sh (or the last clean stop) wrote.
# A restore empties /data first, so a missing database beside a snapshot means one just happened; the
# snapshot becomes the database (D10).
"${VENV_PYTHON}" -m hassette.core.database_snapshot_cli restore \
    "${HASSETTE__DATABASE__PATH}" "${HASSETTE__DATABASE__SHUTDOWN_SNAPSHOT_PATH}" \
    || addon_halt "couldn't restore the database from the backup's snapshot" \
        "Restart the add-on from its page; if that doesn't help, report it at ${ISSUES_URL}"

# Add-on options (D9). Supervisor validates them against config.yaml's schema before the start, and the
# image has no jq, so the venv's Python prints them as shell-quoted assignments.
LOG_LEVEL=""
PYTHON_PACKAGES=""
if [ -f "${OPTIONS_FILE}" ]; then
    options_stdout=$("${VENV_PYTHON}" - "${OPTIONS_FILE}" <<'PY'
import json
import shlex
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    options = json.load(f)
log_level = options.get("log_level") or ""
packages = "\n".join(options.get("python_packages") or [])
print(f"LOG_LEVEL={shlex.quote(log_level)}")
print(f"PYTHON_PACKAGES={shlex.quote(packages)}")
PY
    ) || addon_halt "couldn't read the add-on options (${OPTIONS_FILE})" \
        "Save the add-on's Configuration tab again, then restart the add-on from its page"
    # safe to eval: each value is shlex-quoted, and the script prints only these two names
    eval "${options_stdout}"
fi
if [ -n "${LOG_LEVEL}" ]; then
    export HASSETTE__LOGGING__LOG_LEVEL="${LOG_LEVEL}"
fi
# One requirement per line; empty when the list is, so docker_start.sh's install step has nothing to do.
export HASSETTE_DOCKER_PYTHON_PACKAGES="${PYTHON_PACKAGES}"

# Log which host ports reach the add-on, so a support log shows whether the direct port is exposed (D7).
# Informational only: a failed lookup never stops the start.
# curl's stderr is captured with the body so a failure can say why.
if info_or_error=$(curl -fsS --max-time 5 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    "${SUPERVISOR_URL}/addons/self/info" 2>&1); then
    "${VENV_PYTHON}" - "${info_or_error}" <<'PY' || echo "WARNING: couldn't read the port mappings from Supervisor's reply"
import json
import sys

# network maps each container port to its host port, or to null when the user left it unmapped
network = json.loads(sys.argv[1]).get("data", {}).get("network") or {}
mapped = [f"{port} -> host port {host}" for port, host in network.items() if host]
print("Port mappings: " + (", ".join(mapped) or "none (ingress only)"))
PY
else
    echo "WARNING: couldn't ask Supervisor for the port mappings: ${info_or_error}"
fi

# Announce hassette to the integration through Supervisor discovery once it serves (D13). It runs in the
# background and outlives the exec below; a failed announce is logged and never stops the add-on.
/app/docker/addon/discovery_announce.sh \
    "${SUPERVISOR_URL}" "${HASSETTE__WEB_API__PORT}" "${HASSETTE__WEB_API__TOKEN_FILE}" &

exec /app/scripts/docker_start.sh "$@"

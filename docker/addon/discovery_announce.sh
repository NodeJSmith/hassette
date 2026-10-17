#!/usr/bin/env bash
# The add-on's Supervisor discovery announce (design/specs/129-ha-addon-v01/design.md, D13). run.sh starts it
# in the background before handing off to docker_start.sh. It waits until hassette serves, then tells
# Supervisor how to reach it, so the hass-hassette integration's "Discovered" card only appears once Configure
# can succeed. Every start announces with the token file's current contents, so a rotated token (D8) reaches
# Supervisor, which keeps the latest payload and passes a changed one on to Core.
#
# Usage: discovery_announce.sh <supervisor url> <web api port> <token file>
# Announcing is best-effort: a failure is logged and the add-on keeps running.

set -uo pipefail

SUPERVISOR_URL="$1"
PORT="$2"
TOKEN_FILE="$3"
LIVE_URL="http://127.0.0.1:${PORT}/api/health/live"
POLL_INTERVAL_SECS=2

# No limit of its own: if hassette never serves, the loop ends when the container does.
until curl -fsS --max-time 5 -o /dev/null "${LIVE_URL}" 2>/dev/null; do
    sleep "${POLL_INTERVAL_SECS}"
done

# hassette has written the token file by the time it serves. python3 builds the JSON, so the token is escaped,
# and reads the container's hostname, which Supervisor sets to the add-on's hostname that Core reaches it by
# (D13).
if ! payload=$(python3 - "${PORT}" "${TOKEN_FILE}" <<'PY' 2>&1
import json
import socket
import sys

host, port, token_file = socket.gethostname(), int(sys.argv[1]), sys.argv[2]
try:
    with open(token_file, encoding="utf-8") as f:
        token = f.read().strip()
except OSError as exc:
    sys.exit(str(exc))
if not token:
    sys.exit(f"{token_file} is empty")
print(json.dumps({"service": "hassette", "config": {"host": host, "port": port, "auth_token": token}}))
PY
); then
    echo "WARNING: couldn't announce hassette to Home Assistant (reading ${TOKEN_FILE} failed): ${payload}"
    exit 0
fi

# curl's stderr is captured with the body so a failure can say why.
if ! reply=$(curl -fsS --max-time 10 -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" -H "Content-Type: application/json" \
    --data "${payload}" "${SUPERVISOR_URL}/discovery" 2>&1); then
    echo "WARNING: couldn't announce hassette to Home Assistant through Supervisor discovery: ${reply}"
    exit 0
fi
echo "Announced hassette to Home Assistant; the hassette integration can now be set up from its Discovered card"

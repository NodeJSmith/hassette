#!/usr/bin/env sh

set -eu # no pipefail in busybox ash

# shellcheck disable=SC1091
. /app/.venv/bin/activate

HASSETTE_VERSION=$(uv version --short --directory /app)

echo "Running Hassette version $HASSETTE_VERSION"

APPS="${HASSETTE__APP_DIR:-/apps}"
CONFIG="${HASSETTE__CONFIG_DIR:-/config}"
ALLOW_UNLOCKED_PROJECT="${HASSETTE__ALLOW_UNLOCKED_PROJECT:-0}"

# Debian package is `fd-find`; binary name is usually `fdfind`.
FD_BIN="$(command -v fdfind || command -v fd)"

# Install project deps if present
if [ -f "$APPS/uv.lock" ]; then
    echo "Installing locked project in $APPS"
    uv sync --directory "$APPS" --locked --active
elif [ -f "$APPS/pyproject.toml" ] && [ "$ALLOW_UNLOCKED_PROJECT" = "1" ]; then
    echo "Installing unlocked project in $APPS (HASSETTE__ALLOW_UNLOCKED_PROJECT=1)"
    uv sync --directory "$APPS" --active
fi

echo "Completed sync of found project"

# Build list of roots that exist
ROOTS=""
[ -d "$CONFIG" ] && ROOTS="$ROOTS $CONFIG"
[ -d "$APPS" ] && ROOTS="$ROOTS $APPS"

# Install requirements files (fd ignores .git/.venv/node_modules by default)
if [ -n "$ROOTS" ]; then
    # Find both filenames, deterministic order
    # shellcheck disable=SC2086
    "$FD_BIN" -t f -a -0 'requirements' --extension txt $ROOTS |
        sort -z |
        while IFS= read -r req; do
            # Skip empty files (fd doesn't have a simple portable "non-empty" filter)
            [ -s "$req" ] || continue
            echo "Installing requirements from $req"
            uv pip install -r "$req"
        done
fi

echo "Completed installation of found requirements.txt files"

if [ -n "${HASSETTE_VERSION:-}" ]; then
    # ensure correct version of hassette is still installed
    echo "Ensuring hassette version ${HASSETTE_VERSION} is installed"
    uv pip install "hassette==${HASSETTE_VERSION}"
else
    echo "No specific hassette version specified"
fi

exec hassette "$@"

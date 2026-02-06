#!/usr/bin/env sh

set -eu # no pipefail in busybox ash

# shellcheck disable=SC1091
. /app/.venv/bin/activate

HASSETTE_VERSION=$(uv version --short --directory /app)

echo "Running Hassette version $HASSETTE_VERSION"

# APP_DIR is where we start looking for actual *.py files that contain App/AppSync classes
# PROJECT_DIR is where to look for a uv.lock or pyproject.toml file for a package

APP_DIR="${HASSETTE__APP_DIR:-/apps}"
PROJECT_DIR="${HASSETTE__PROJECT_DIR:-/apps}"

CONFIG="${HASSETTE__CONFIG_DIR:-/config}"
ALLOW_UNLOCKED_PROJECT="${HASSETTE__ALLOW_UNLOCKED_PROJECT:-0}"

# Debian package is `fd-find`; binary name is usually `fdfind`.
FD_BIN="$(command -v fdfind || command -v fd)"

# Install project deps if present
if [ -f "$PROJECT_DIR/uv.lock" ]; then
    echo "Installing locked project in $PROJECT_DIR"
    uv sync --directory "$PROJECT_DIR" --locked --active
elif [ -f "$PROJECT_DIR/pyproject.toml" ] && [ "$ALLOW_UNLOCKED_PROJECT" = "1" ]; then
    echo "Installing unlocked project in $PROJECT_DIR (HASSETTE__ALLOW_UNLOCKED_PROJECT=1)"
    uv sync --directory "$PROJECT_DIR" --active
fi

echo "Completed sync of found project"

# Build list of roots that exist
ROOTS=""
[ -d "$CONFIG" ] && ROOTS="$ROOTS $CONFIG"
[ -d "$APP_DIR" ] && ROOTS="$ROOTS $APP_DIR"

# Install requirements files (fd ignores .git/.venv/node_modules by default)
if [ -n "$ROOTS" ]; then
    # Find both filenames, deterministic order
    # shellcheck disable=SC2086
    "$FD_BIN" -t f -a -0 'requirements' --extension txt $ROOTS |
        sort -z | tr '\0' '\n' |
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
    uv pip install /app
else
    echo "No specific hassette version specified"
fi

exec hassette "$@"

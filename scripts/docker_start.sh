#!/usr/bin/env bash

set -eu

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

found_files=0

# Install requirements files (fd ignores .git/.venv/node_modules by default)
if [ -n "$ROOTS" ]; then
    # shellcheck disable=SC2086
    while IFS= read -r req; do
        [ -s "$req" ] || continue
        found_files=$((found_files + 1))
        echo "Installing requirements from $req"
        uv pip install -r "$req"
    done < <("$FD_BIN" -t f -a -0 'requirements' --extension txt $ROOTS | sort -z | tr '\0' '\n')
fi

echo "Completed installation of $found_files found requirements.txt files"

if [ -n "${HASSETTE_VERSION:-}" ]; then
    # ensure correct version of hassette is still installed
    echo "Ensuring hassette version ${HASSETTE_VERSION} is installed"
    uv pip install /app
else
    echo "No specific hassette version specified"
fi

exec hassette "$@"

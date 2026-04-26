#!/usr/bin/env bash

set -euo pipefail

# ── startup timing ──────────────────────────────────────────────────────────
STARTUP_EPOCH=$(date +%s%3N)
log_phase() {
    local elapsed
    elapsed=$(( $(date +%s%3N) - STARTUP_EPOCH ))
    printf "[%7dms] %s\n" "$elapsed" "$1"
}

log_phase "entrypoint started"

# shellcheck disable=SC1091
. /app/.venv/bin/activate
log_phase "venv activated"

# Validate venv health by importing hassette — catches corrupt images
HASSETTE_VERSION=$(python -c "import importlib.metadata; print(importlib.metadata.version('hassette'))" 2>&1) || {
    echo "ERROR: Failed to import hassette — the Docker image may be corrupt."
    echo "       Details: ${HASSETTE_VERSION}"
    exit 1
}
log_phase "venv health check passed (v${HASSETTE_VERSION})"

# APP_DIR is where we start looking for actual *.py files that contain App/AppSync classes
# PROJECT_DIR is where to look for a uv.lock or pyproject.toml file for a package
APP_DIR="${HASSETTE__APP_DIR:-/apps}"
PROJECT_DIR="${HASSETTE__PROJECT_DIR:-/apps}"
CONFIG="${HASSETTE__CONFIG_DIR:-/config}"
INSTALL_DEPS="${HASSETTE__INSTALL_DEPS:-0}"
PRUNE_UV_CACHE="${HASSETTE__PRUNE_UV_CACHE:-1}"
CONSTRAINTS="/app/constraints.txt"

# Debian package is `fd-find`; binary name is usually `fdfind`.
FD_BIN="$(command -v fdfind || command -v fd || true)"
if [ -z "$FD_BIN" ] && [ "${INSTALL_DEPS}" = "1" ]; then
    echo "WARNING: fd (fdfind) not found — HASSETTE__INSTALL_DEPS=1 will not work."
elif [ -z "$FD_BIN" ]; then
    echo "NOTE: fd (fdfind) not found — if you enable HASSETTE__INSTALL_DEPS=1 later, it will require fd."
fi

# Deprecation warning for removed env var
if [ -n "${HASSETTE__ALLOW_UNLOCKED_PROJECT:-}" ]; then
    echo "WARNING: HASSETTE__ALLOW_UNLOCKED_PROJECT is deprecated and has no effect."
    echo "         Migration options:"
    echo "           1. Run 'uv lock' locally, commit uv.lock, and mount your project."
    echo "           2. Use HASSETTE__INSTALL_DEPS=1 with a requirements.txt file."
fi

# ── helper: run a uv command with timeout and friendly error messages ─────────
# Usage: run_uv_install <timeout_seconds> <conflict_type> <uv args...>
# conflict_type: "export", "project", or "requirements"
run_uv_install() {
    local timeout_secs="$1"
    local conflict_type="$2"
    shift 2

    local uv_log
    uv_log=$(mktemp /tmp/uv-output.XXXXXX)

    # Stream live output AND capture to file for error replay.
    # Temporarily disable set -e so the pipeline doesn't abort the function,
    # then capture PIPESTATUS immediately (it's reset by the next command).
    set +e
    timeout "${timeout_secs}" uv "$@" 2>&1 | tee "${uv_log}"
    local -a pipe_status=("${PIPESTATUS[@]}")
    set -e
    local exit_code="${pipe_status[0]}"
    local tee_code="${pipe_status[1]:-0}"

    if [ "${exit_code}" -eq 0 ] && [ "${tee_code}" -eq 0 ]; then
        rm -f "${uv_log}"
        return 0
    fi

    # tee failure (disk full, permission denied) — warn but use the uv exit code for decision
    if [ "${tee_code}" -ne 0 ] && [ "${exit_code}" -eq 0 ]; then
        echo "WARNING: output capture failed (tee exit ${tee_code}) — install may have succeeded but logs are incomplete"
        rm -f "${uv_log}"
        return 0
    fi

    if [ "${exit_code}" -eq 124 ]; then
        rm -f "${uv_log}"
        echo "ERROR: dependency install timed out after ${timeout_secs}s"
        exit 1
    fi

    # User-friendly error banner — uv output was already streamed live above
    echo ""
    if [ "${conflict_type}" = "export" ]; then
        echo "─────────────────────────────────────────────────────────"
        echo "  EXPORT FAILED"
        echo ""
        echo "  Could not export your project's dependencies."
        echo "  Common causes: local path deps, git deps not reachable,"
        echo "  or a lockfile that needs regenerating."
        echo ""
        echo "  To fix: run 'uv lock' locally, commit uv.lock, and restart."
        echo "  If your project has local path deps, use the custom image"
        echo "  build pattern instead."
        echo "─────────────────────────────────────────────────────────"
    elif [ "${conflict_type}" = "project" ]; then
        echo "─────────────────────────────────────────────────────────"
        echo "  DEPENDENCY CONFLICT"
        echo ""
        echo "  Your project's dependencies conflict with this version"
        echo "  of Hassette. This usually means your uv.lock was generated"
        echo "  against a different Hassette version than this image."
        echo ""
        echo "  To fix: run 'uv lock' locally, commit uv.lock, and restart."
        echo "─────────────────────────────────────────────────────────"
    else
        echo "─────────────────────────────────────────────────────────"
        echo "  DEPENDENCY CONFLICT"
        echo ""
        echo "  A requirements.txt dependency conflicts with this version"
        echo "  of Hassette."
        echo ""
        echo "  To fix: relax the version pin in your requirements.txt, or"
        echo "  check which version hassette requires:"
        echo "    cat /app/constraints.txt | grep <package>"
        echo "─────────────────────────────────────────────────────────"
    fi

    rm -f "${uv_log}"
    echo "ERROR: dependency install failed (exit ${exit_code})"
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Project-based install (export deps → install with constraints → install package)
# ---------------------------------------------------------------------------
if [ -f "$PROJECT_DIR/uv.lock" ]; then
    log_phase "project install: starting (from $PROJECT_DIR)"

    # Temp files — cleaned up on exit (including early termination)
    user_deps_file=$(mktemp /tmp/user-deps.XXXXXX)
    tmp_project=$(mktemp -d /tmp/project-build.XXXXXX)
    trap 'rm -f "${user_deps_file}"; rm -rf "${tmp_project}"' EXIT

    log_phase "project install: exporting locked deps"
    run_uv_install 300 "export" export \
        --no-hashes --frozen \
        --directory "$PROJECT_DIR" \
        --no-default-groups \
        --no-dev --no-editable --no-emit-project \
        --output-file "${user_deps_file}"

    log_phase "project install: installing deps with constraints"
    run_uv_install 300 "project" pip install \
        -r "${user_deps_file}" \
        -c "$CONSTRAINTS"

    log_phase "project install: installing project package"
    cp -a "$PROJECT_DIR"/. "$tmp_project"/
    run_uv_install 120 "project" pip install \
        --no-deps "$tmp_project"

    log_phase "project install: complete"

elif [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    log_phase "project install: skipped (pyproject.toml found but no uv.lock — run 'uv lock' to generate a lockfile, then restart)"
else
    log_phase "project install: skipped (no project in $PROJECT_DIR)"
fi

# ---------------------------------------------------------------------------
# 2. Requirements.txt discovery (only when HASSETTE__INSTALL_DEPS=1)
# ---------------------------------------------------------------------------
if [ "${INSTALL_DEPS}" = "1" ]; then
    log_phase "requirements install: starting"
    if [ -z "$FD_BIN" ]; then
        echo "ERROR: HASSETTE__INSTALL_DEPS=1 but fd is not installed in this image."
        exit 1
    fi

    ROOTS=()
    [ -d "$CONFIG" ] && ROOTS+=("$CONFIG")
    [ -d "$APP_DIR" ] && ROOTS+=("$APP_DIR")

    found_files=0

    if [ "${#ROOTS[@]}" -gt 0 ]; then
        # Exact match for requirements.txt only; NUL-safe read; max-depth 5
        while IFS= read -r -d '' req; do
            [ -s "$req" ] || continue
            found_files=$((found_files + 1))
            echo "Installing requirements from $req (with constraints)..."
            run_uv_install 120 "requirements" pip install \
                -r "$req" \
                -c "$CONSTRAINTS"
        done < <("$FD_BIN" -t f -a -0 --max-depth 5 '^requirements\.txt$' "${ROOTS[@]}" | sort -z)
    fi

    log_phase "requirements install: complete ($found_files file(s))"
else
    # Hint if user tried a truthy value other than "1"
    case "${INSTALL_DEPS}" in
        true|yes|on|TRUE|YES|ON)
            echo "WARNING: HASSETTE__INSTALL_DEPS='${INSTALL_DEPS}' is not recognized — use '1' to enable. Your requirements.txt files will NOT be installed."
            ;;
    esac
    log_phase "requirements install: disabled (set HASSETTE__INSTALL_DEPS=1 to enable)"
fi

if [ "${PRUNE_UV_CACHE}" = "1" ]; then
    log_phase "uv cache prune: starting"
    uv cache prune || echo "WARNING: uv cache prune failed — continuing anyway"
    log_phase "uv cache prune: complete"
else
    case "${PRUNE_UV_CACHE}" in
        true|yes|on|TRUE|YES|ON)
            echo "WARNING: HASSETTE__PRUNE_UV_CACHE='${PRUNE_UV_CACHE}' is not recognized — use '1' to enable or '0' to disable. Cache will NOT be pruned."
            ;;
    esac
    log_phase "uv cache prune: disabled"
fi

log_phase "handing off to hassette"
exec hassette "$@"

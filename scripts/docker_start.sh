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

# Script-only settings live outside the HASSETTE__ namespace, which is reserved for Hassette settings.
INSTALL_DEPS="${HASSETTE_DOCKER_INSTALL_DEPS:-0}"
PRUNE_UV_CACHE="${HASSETTE_DOCKER_PRUNE_UV_CACHE:-1}"
RETRY_DELAY="${HASSETTE_DOCKER_RETRY_DELAY:-300}"
CONSTRAINTS="/app/constraints.txt"
IMAGE_APP_DIR="/app"  # Hassette's own install, with its own pyproject.toml and uv.lock; never a user project
LEGACY_APPS_DIR="/apps"

REMEDY_FILE="Fix the file named above, then run: docker restart <container>"
REMEDY_ENV="Fix the environment variable in your compose file, then run: docker compose up -d
  (docker restart keeps the old environment)"
REMEDY_IMAGE="Pull the image again: docker compose pull && docker compose up -d"
REMEDY_ARGS="Fix the container's command arguments in your compose file, then run: docker compose up -d"

# Temp files, removed on exit and before a halt's idle.
user_deps_file=""
tmp_project=""
cleanup_tmp() {
    if [ -n "${user_deps_file}" ]; then rm -f "${user_deps_file}"; fi
    if [ -n "${tmp_project}" ]; then rm -rf "${tmp_project}"; fi
    user_deps_file=""
    tmp_project=""
}
trap cleanup_tmp EXIT

# ── helper: halt on an unrecoverable startup error ────────────────────────────
# Usage: halt <exit_code> <what failed> <remedy>
# Docker restarts a container that exits non-zero, so exiting at once would hot-loop (and repeat any
# dependency install). Instead: print one banner, idle RETRY_DELAY seconds, then exit so Docker
# retries, which still heals a transient cause (a mount not ready yet, the network).
halt() {
    local exit_code="$1" what="$2" remedy="$3"
    cleanup_tmp
    echo ""
    echo "─────────────────────────────────────────────────────────"
    echo "  HASSETTE CAN'T START: ${what}"
    echo ""
    echo "  ${remedy}"
    if [ "${RETRY_DELAY}" != "0" ]; then
        echo ""
        echo "  Retrying in ${RETRY_DELAY}s (HASSETTE_DOCKER_RETRY_DELAY; 0 exits at once)."
    fi
    echo "─────────────────────────────────────────────────────────"
    if [ "${RETRY_DELAY}" != "0" ]; then
        # sleep in the background so `docker stop` (SIGTERM, forwarded by tini) ends the idle at once
        sleep "${RETRY_DELAY}" &
        HALT_SLEEP_PID=$!
        trap 'kill "${HALT_SLEEP_PID}" 2>/dev/null; exit 143' TERM INT
        wait "${HALT_SLEEP_PID}" || true
    fi
    exit "${exit_code}"
}

# shellcheck disable=SC1091
. /app/.venv/bin/activate
log_phase "venv activated"

# Validate venv health by importing hassette — catches corrupt images
HASSETTE_VERSION=$(python -c "import importlib.metadata; print(importlib.metadata.version('hassette'))" 2>&1) || {
    echo "ERROR: Failed to import hassette — the Docker image may be corrupt."
    echo "       Details: ${HASSETTE_VERSION}"
    halt 1 "the Docker image is corrupt" "${REMEDY_IMAGE}"
}
log_phase "venv health check passed (v${HASSETTE_VERSION})"

# ── config check and locations ────────────────────────────────────────────────
# Hassette resolves its own config, apps and project locations, from the same args as the final
# `hassette run`, and rejects an invalid config before anything is installed.
check_args=()
for arg in "$@"; do
    # the container may itself be asked for --check; passing it twice is a usage error
    [ "${arg}" = "--check" ] || check_args+=("${arg}")
done
set +e
# stdout is only shell-quoted KEY=VALUE lines (see check_config in hassette/cli/commands/run.py);
# the check's error text goes to stderr, straight to the container log
check_stdout=$(hassette run --check "${check_args[@]}")
check_code=$?
set -e

CONFIG_DIR=""
CONFIG_HOME=""
APPS_DIR=""
CONFIG_ERROR_SOURCE=""
while IFS= read -r line; do
    case "${line}" in
        CONFIG_DIR=* | CONFIG_HOME=* | APPS_DIR=* | CONFIG_ERROR_SOURCE=*)
            # safe to eval: `hassette run --check` shlex-quotes each value, and only these names pass
            eval "${line}"
            ;;
    esac
done <<< "${check_stdout}"

if [ "${check_code}" -eq 78 ]; then
    remedy="${REMEDY_FILE}"
    if [ "${CONFIG_ERROR_SOURCE}" = "environment" ]; then  # ERROR_SOURCE_ENVIRONMENT in hassette/config/checks.py
        remedy="${REMEDY_ENV}"
    fi
    halt 78 "the configuration is invalid (see above)" "${remedy}"
elif [ "${check_code}" -ne 0 ]; then
    halt "${check_code}" "'hassette run --check' failed (see above)" "${REMEDY_ARGS}"
fi

if [ -z "${CONFIG_DIR}" ] || [ -z "${CONFIG_HOME}" ] || [ -z "${APPS_DIR}" ]; then
    # args like --help or --version print instead of checking, and need nothing installed
    log_phase "no config locations from 'hassette run --check'; skipping dependency installs"
    exec hassette run "$@"
fi
log_phase "config checked (config dir ${CONFIG_DIR}, apps dir ${APPS_DIR})"

# Project dir: explicit, else the nearest directory at or above the apps dir holding a pyproject.toml
# (the uv/pytest walk-up), else the config home.
find_project_dir() {
    local dir="${APPS_DIR}"
    while [ "${dir}" != "/" ] && [ "${dir}" != "${IMAGE_APP_DIR}" ]; do
        if [ -f "${dir}/pyproject.toml" ]; then
            echo "${dir}"
            return
        fi
        dir="$(dirname "${dir}")"
    done
    echo "${CONFIG_HOME}"
}
PROJECT_DIR="${HASSETTE_DOCKER_PROJECT_DIR:-$(find_project_dir)}"

# Apps used to live in a separate /apps volume; they now default to <config dir>/apps.
case "${APPS_DIR}/" in  # the trailing / lets a dir match its own "<dir>/"* pattern
    "${LEGACY_APPS_DIR}"/*) ;;
    *)
        if [ -d "${LEGACY_APPS_DIR}" ] && [ -n "$(ls -A "${LEGACY_APPS_DIR}" 2>/dev/null)" ]; then
            echo "NOTE: ${LEGACY_APPS_DIR} has files, but Hassette loads apps from ${APPS_DIR}."
            echo "      Move your apps to ${APPS_DIR}, or set HASSETTE__APPS__DIRECTORY=${LEGACY_APPS_DIR}."
        fi
        ;;
esac

# Debian package is `fd-find`; binary name is usually `fdfind`.
FD_BIN="$(command -v fdfind || command -v fd || true)"
if [ -z "$FD_BIN" ] && [ "${INSTALL_DEPS}" = "1" ]; then
    echo "WARNING: fd (fdfind) not found — HASSETTE_DOCKER_INSTALL_DEPS=1 will not work."
elif [ -z "$FD_BIN" ]; then
    echo "NOTE: fd (fdfind) not found — if you enable HASSETTE_DOCKER_INSTALL_DEPS=1 later, it will require fd."
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
        halt 1 "the dependency install timed out" "Check the container's network access."
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
    halt 1 "a dependency conflict (see above)" "${REMEDY_FILE}"
}

# ---------------------------------------------------------------------------
# 1. Project-based install (export deps → install with constraints → install package)
# ---------------------------------------------------------------------------
if [ -f "$PROJECT_DIR/uv.lock" ]; then
    log_phase "project install: starting (from $PROJECT_DIR)"

    user_deps_file=$(mktemp /tmp/user-deps.XXXXXX)
    tmp_project=$(mktemp -d /tmp/project-build.XXXXXX)

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

    # Explicit cleanup — the EXIT trap never fires on the happy path because
    # the script ends in `exec`, which replaces the shell process instead of exiting it.
    cleanup_tmp

    log_phase "project install: complete"

elif [ -f "$PROJECT_DIR/pyproject.toml" ]; then
    log_phase "project install: skipped (pyproject.toml found but no uv.lock — run 'uv lock' to generate a lockfile, then restart)"
else
    log_phase "project install: skipped (no project in $PROJECT_DIR)"
fi

# ---------------------------------------------------------------------------
# 2. Requirements.txt discovery (only when HASSETTE_DOCKER_INSTALL_DEPS=1)
# ---------------------------------------------------------------------------
if [ "${INSTALL_DEPS}" = "1" ]; then
    log_phase "requirements install: starting"
    if [ -z "$FD_BIN" ]; then
        echo "ERROR: HASSETTE_DOCKER_INSTALL_DEPS=1 but fd is not installed in this image."
        halt 1 "fd is missing from the image" "${REMEDY_IMAGE}"
    fi

    ROOTS=()
    [ -d "$CONFIG_DIR" ] && ROOTS+=("$CONFIG_DIR")
    case "${APPS_DIR}/" in
        "${CONFIG_DIR}"/*) ;;  # already scanned under the config dir
        *) [ -d "$APPS_DIR" ] && ROOTS+=("$APPS_DIR") ;;
    esac

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
            echo "WARNING: HASSETTE_DOCKER_INSTALL_DEPS='${INSTALL_DEPS}' is not recognized — use '1' to enable. Your requirements.txt files will NOT be installed."
            ;;
    esac
    log_phase "requirements install: disabled (set HASSETTE_DOCKER_INSTALL_DEPS=1 to enable)"
fi

if [ "${PRUNE_UV_CACHE}" = "1" ]; then
    log_phase "uv cache prune: starting"
    uv cache prune || echo "WARNING: uv cache prune failed — continuing anyway"
    log_phase "uv cache prune: complete"
else
    case "${PRUNE_UV_CACHE}" in
        true|yes|on|TRUE|YES|ON)
            echo "WARNING: HASSETTE_DOCKER_PRUNE_UV_CACHE='${PRUNE_UV_CACHE}' is not recognized — use '1' to enable or '0' to disable. Cache will NOT be pruned."
            ;;
    esac
    log_phase "uv cache prune: disabled"
fi

log_phase "handing off to hassette"
exec hassette run "$@"

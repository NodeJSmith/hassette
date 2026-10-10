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
TMP_ROOT="${TMPDIR:-/tmp}"

# Per-step uv timeouts (seconds) and requirements.txt search depth
UV_EXPORT_TIMEOUT_SECS=300
UV_PROJECT_DEPS_TIMEOUT_SECS=300
UV_PROJECT_PACKAGE_TIMEOUT_SECS=120
UV_REQUIREMENTS_TIMEOUT_SECS=120
REQUIREMENTS_MAX_DEPTH=5

REMEDY_DEPS="Fix the dependency file named above, then run: docker restart <container>"
REMEDY_CONFIG="Fix the setting named above (in its file or your compose environment), then run: docker compose up -d
  (docker restart keeps the old environment)"
REMEDY_IMAGE="Pull the image again: docker compose pull && docker compose up -d"
REMEDY_UNEXPECTED="Check the error above: fix the container's command arguments if it names one,
  otherwise report it at https://github.com/NodeJSmith/hassette/issues"
EX_CONFIG=78  # EX_CONFIG in hassette/cli/commands/run.py; a test keeps them in sync
# Args that make `hassette run` print and exit instead of starting: cyclopts' help flags and the
# root app's version_flags (hassette/cli/__init__.py). A test keeps this list in sync.
PASSTHROUGH_FLAGS=(--help -h --version -v)

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

# Help and version args (anywhere in the args) print and exit, so they need no check and nothing installed.
for arg in "$@"; do
    for flag in "${PASSTHROUGH_FLAGS[@]}"; do
        if [ "${arg}" = "${flag}" ]; then
            exec hassette run "$@"
        fi
    done
done

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
while IFS= read -r line; do
    case "${line}" in
        CONFIG_DIR=* | CONFIG_HOME=* | APPS_DIR=*)
            # safe to eval: `hassette run --check` shlex-quotes each value, and only these names pass
            eval "${line}"
            ;;
    esac
done <<< "${check_stdout}"

# Recreating the container rereads both its environment and its mounted files, so one remedy
# covers a config error from either.
if [ "${check_code}" -eq "${EX_CONFIG}" ]; then
    halt "${EX_CONFIG}" "the configuration is invalid (see above)" "${REMEDY_CONFIG}"
elif [ "${check_code}" -ne 0 ]; then
    halt "${check_code}" "'hassette run --check' failed unexpectedly (see above)" "${REMEDY_UNEXPECTED}"
fi

# Success is exit 0 with every location printed; anything less never passes for a checked config.
if [ -z "${CONFIG_DIR}" ] || [ -z "${CONFIG_HOME}" ] || [ -z "${APPS_DIR}" ]; then
    halt 1 "'hassette run --check' exited 0 without printing the config locations" "${REMEDY_UNEXPECTED}"
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

# Debian package is `fd-find`; binary name is usually `fdfind`.
FD_BIN="$(command -v fdfind || command -v fd || true)"
if [ -z "$FD_BIN" ] && [ "${INSTALL_DEPS}" = "1" ]; then
    echo "WARNING: fd (fdfind) not found — HASSETTE_DOCKER_INSTALL_DEPS=1 will not work."
elif [ -z "$FD_BIN" ]; then
    echo "NOTE: fd (fdfind) not found — if you enable HASSETTE_DOCKER_INSTALL_DEPS=1 later, it will require fd."
fi

# ── helper: user-facing banner for a failed uv command ──────────────────────
# Usage: print_install_failure_banner <failure_type>
# failure_type (valid set): "export" | "project" | "requirements"
print_install_failure_banner() {
    local failure_type="$1"

    echo ""
    case "${failure_type}" in
        export)
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
            ;;
        project)
            echo "─────────────────────────────────────────────────────────"
            echo "  DEPENDENCY CONFLICT"
            echo ""
            echo "  Your project's dependencies conflict with this version"
            echo "  of Hassette. This usually means your uv.lock was generated"
            echo "  against a different Hassette version than this image."
            echo ""
            echo "  To fix: run 'uv lock' locally, commit uv.lock, and restart."
            echo "─────────────────────────────────────────────────────────"
            ;;
        requirements)
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
            ;;
        *)
            echo "BUG: print_install_failure_banner got unknown failure type '${failure_type}'"
            ;;
    esac
}

# ── helper: run a uv command with timeout and friendly error messages ─────────
# Usage: run_uv_install <timeout_seconds> <failure_type> <uv args...>
# failure_type: see print_install_failure_banner for the valid set
run_uv_install() {
    local timeout_secs="$1"
    local failure_type="$2"
    shift 2

    # uv's output streams straight to the container log; set -e is off so a failure reaches the checks below
    local exit_code
    set +e
    timeout "${timeout_secs}" uv "$@" 2>&1
    exit_code=$?
    set -e

    if [ "${exit_code}" -eq 0 ]; then
        return 0
    fi

    if [ "${exit_code}" -eq 124 ]; then
        echo "ERROR: dependency install timed out after ${timeout_secs}s"
        halt 1 "the dependency install timed out" "Check the container's network access."
    fi

    print_install_failure_banner "${failure_type}"
    echo "ERROR: dependency install failed (exit ${exit_code})"
    halt 1 "a dependency conflict (see above)" "${REMEDY_DEPS}"
}

# ---------------------------------------------------------------------------
# 1. Project-based install (export deps → install with constraints → install package)
# ---------------------------------------------------------------------------
if [ -f "$PROJECT_DIR/uv.lock" ]; then
    log_phase "project install: starting (from $PROJECT_DIR)"

    user_deps_file=$(mktemp "${TMP_ROOT}/user-deps.XXXXXX")
    tmp_project=$(mktemp -d "${TMP_ROOT}/project-build.XXXXXX")

    log_phase "project install: exporting locked deps"
    run_uv_install "$UV_EXPORT_TIMEOUT_SECS" "export" export \
        --no-hashes --frozen \
        --directory "$PROJECT_DIR" \
        --no-default-groups \
        --no-dev --no-editable --no-emit-project \
        --output-file "${user_deps_file}"

    log_phase "project install: installing deps with constraints"
    run_uv_install "$UV_PROJECT_DEPS_TIMEOUT_SECS" "project" pip install \
        -r "${user_deps_file}" \
        -c "$CONSTRAINTS"

    log_phase "project install: installing project package"
    cp -a "$PROJECT_DIR"/. "$tmp_project"/
    run_uv_install "$UV_PROJECT_PACKAGE_TIMEOUT_SECS" "project" pip install \
        --no-deps "$tmp_project"

    # Explicit cleanup — the EXIT trap never fires on the happy path because
    # the script ends in `exec`, which replaces the shell process instead of exiting it.
    cleanup_tmp

    log_phase "project install: complete"

    # A build backend misconfiguration can install a package with nothing importable in it while
    # every install step exits 0. App loading reads the apps dir directly, so warn rather than halt:
    # most deployments still run, but the packaging is broken. The import names come from the
    # installed distribution's RECORD, not [project].name, since the two may legitimately differ.
    # -P keeps the cwd off sys.path, so a module there can't mask a broken install.
    project_package_problem=$(python -P -c '
import importlib.metadata
import importlib.util
import sys
import tomllib

with open(sys.argv[1], "rb") as f:
    name = tomllib.load(f).get("project", {}).get("name")
if not name:
    sys.exit()
try:
    files = importlib.metadata.distribution(name).files or []
except importlib.metadata.PackageNotFoundError:
    print(f"distribution {name!r} is not installed")
    sys.exit()
top_level_names = set()
for path in files:
    top = path.parts[0]
    if len(path.parts) == 1:
        if top.endswith((".py", ".so", ".pyd")):
            top_level_names.add(top.split(".")[0])
    # ".." entries are files installed outside site-packages, such as console scripts in bin/
    elif top not in ("..", "__pycache__") and not top.endswith((".dist-info", ".data")):
        top_level_names.add(top)
missing = sorted(t for t in top_level_names if importlib.util.find_spec(t) is None)
if not top_level_names:
    print(f"distribution {name!r} installed no importable modules")
elif missing:
    print(f"distribution {name!r} ships {missing} but they are not importable")
' "$PROJECT_DIR/pyproject.toml" || echo "NOTE: skipped the project package check (it failed; see above)" >&2)
    if [ -n "${project_package_problem}" ]; then
        echo "WARNING: installed project package is misconfigured: ${project_package_problem} — check [build-system] / [tool.uv.build-backend] in pyproject.toml (apps under HASSETTE__APPS__DIRECTORY still load)"
    fi

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
        # Exact match for requirements.txt only; NUL-safe read; depth-limited
        while IFS= read -r -d '' req; do
            [ -s "$req" ] || continue
            found_files=$((found_files + 1))
            echo "Installing requirements from $req (with constraints)..."
            run_uv_install "$UV_REQUIREMENTS_TIMEOUT_SECS" "requirements" pip install \
                -r "$req" \
                -c "$CONSTRAINTS"
        done < <("$FD_BIN" -t f -a -0 --max-depth "$REQUIREMENTS_MAX_DEPTH" '^requirements\.txt$' "${ROOTS[@]}" | sort -z)
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

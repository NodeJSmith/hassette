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
# "addon" under the Home Assistant add-on, whose glue sets it; every add-on-only behavior below is gated on it
RUNTIME="${HASSETTE_DOCKER_RUNTIME:-}"
case "${RUNTIME}" in
    "" | addon) ;;
    *) echo "WARNING: HASSETTE_DOCKER_RUNTIME='${RUNTIME}' is not recognized — only 'addon' is. Using Docker behavior." ;;
esac
CONSTRAINTS="/app/constraints.txt"
IMAGE_APP_DIR="/app"  # Hassette's own install, with its own pyproject.toml and uv.lock; never a user project
TMP_ROOT="${TMPDIR:-/tmp}"

# Per-step uv timeouts (seconds) and requirements.txt search depth
UV_EXPORT_TIMEOUT_SECS=300
UV_PROJECT_DEPS_TIMEOUT_SECS=300
UV_PROJECT_PACKAGE_TIMEOUT_SECS=120
UV_REQUIREMENTS_TIMEOUT_SECS=120
REQUIREMENTS_MAX_DEPTH=5

# Directories never needed to build the project package, skipped when copying it to the temp build
# dir. A dev checkout's in-tree .venv alone can be hundreds of MB, copied on every start.
# Environment dirs are anchored to the project root ("./" prefix), since a nested directory with the
# same name can be a real subpackage (e.g. src/mylib/venv); caches are skipped at any depth.
# .git stays: VCS-versioned build backends (setuptools-scm, hatch-vcs) read it.
PROJECT_COPY_EXCLUDES=(./.venv ./venv ./node_modules __pycache__ .mypy_cache .ruff_cache .pytest_cache)

# uv's cause line when it couldn't connect to an index or download URL (DNS, refused, timed out). The exit code
# doesn't tell this apart from a resolution failure: uv exits 2 for a direct fetch but 1 when the fetch was for a
# build requirement, which it reports as "No solution found". A resolution failure, a package missing from the
# index and an HTTP error status (a 404 URL, which uv prints as "Failed to fetch" too) never print these lines.
UV_NETWORK_ERROR_PATTERN='error sending request for url|operation timed out'

ISSUES_URL="https://github.com/NodeJSmith/hassette/issues"
if [ "${RUNTIME}" = "addon" ]; then
    REMEDY_DEPS="Fix the dependency file named above, then restart the add-on from its page"
    REMEDY_CONFIG="Fix the setting named above, then restart the add-on from its page"
    REMEDY_IMAGE="Update or reinstall the add-on; if that doesn't help, report it at ${ISSUES_URL}"
    REMEDY_UNEXPECTED="Check the error above and report it at ${ISSUES_URL}"
else
    REMEDY_DEPS="Fix the dependency file named above, then run: docker restart <container>"
    REMEDY_CONFIG="Fix the setting named above (in its file or your compose environment), then run: docker compose up -d
  (docker restart keeps the old environment)"
    REMEDY_IMAGE="Pull the image again: docker compose pull && docker compose up -d"
    REMEDY_UNEXPECTED="Check the error above: fix the container's command arguments if it names one,
  otherwise report it at ${ISSUES_URL}"
fi
# Only Docker halts on a network failure (the add-on installs from the uv cache or starts degraded), but it's set
# for both so a future add-on halt can't trip set -u
REMEDY_NETWORK="Check the container's network access (DNS and the route to the package index)"
EX_CONFIG=78  # EX_CONFIG in hassette/cli/commands/run.py; a test keeps them in sync
# Args that make `hassette run` print and exit instead of starting: cyclopts' help flags and the
# root app's version_flags (hassette/cli/__init__.py). A test keeps this list in sync.
PASSTHROUGH_FLAGS=(--help -h --version -v)

# Temp files, removed on exit and before a halt's idle.
user_deps_file=""
tmp_project=""
uv_log_file=""
cleanup_tmp() {
    if [ -n "${user_deps_file}" ]; then rm -f "${user_deps_file}"; fi
    if [ -n "${tmp_project}" ]; then rm -rf "${tmp_project}"; fi
    # run_uv_install removes its own log; this covers a stop or halt landing mid-step
    if [ -n "${uv_log_file}" ]; then rm -f "${uv_log_file}"; fi
    user_deps_file=""
    tmp_project=""
    uv_log_file=""
}
trap cleanup_tmp EXIT

# ── stop handling ─────────────────────────────────────────────────────────────
# `docker stop` (and Supervisor's add-on stop) sends TERM, which tini forwards to this script only. A stop exits 0
# whatever phase it lands in, never 143, which Supervisor logs as a failure. Bash runs a trap only once the
# foreground command finishes, so the long steps (uv, the halt idle) run in the background under `wait`, which a
# trapped signal interrupts at once; STOP_WAIT_PID is that step. The short foreground steps (the config check, the
# project copy, fd, the cache prune) delay the exit until they finish. For uv, STOP_WAIT_PID is the subshell running
# uv_with_log, so killing it leaves timeout, uv and tee running; they end with the container when tini exits.
STOP_WAIT_PID=""
on_stop() {
    if [ -n "${STOP_WAIT_PID}" ]; then kill "${STOP_WAIT_PID}" 2>/dev/null || true; fi
    exit 0
}
trap on_stop TERM INT

# Usage: wait_interruptibly <command...>
# Runs the command in the background and returns its exit code, so a stop ends the script without waiting for it.
wait_interruptibly() {
    local code=0
    "$@" &
    STOP_WAIT_PID=$!
    wait "${STOP_WAIT_PID}" || code=$?
    STOP_WAIT_PID=""
    return "${code}"
}

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
        wait_interruptibly sleep "${RETRY_DELAY}" || true  # the idle's own status doesn't matter; a stop exits in on_stop
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
            echo "  of Hassette or one of its dependencies (named above)."
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

# ── helper: user-facing banner for a degraded start ───────────────────────────
# Installs skipped because the network was down and the uv cache couldn't stand in (add-on only).
SKIPPED_INSTALLS=()
print_degraded_start_banner() {
    echo ""
    echo "─────────────────────────────────────────────────────────"
    echo "  HASSETTE IS STARTING WITHOUT SOME DEPENDENCIES"
    echo ""
    echo "  The package index couldn't be reached and the uv cache"
    echo "  doesn't hold everything needed, so these installs didn't run:"
    local label
    for label in "${SKIPPED_INSTALLS[@]}"; do
        echo "    - ${label}"
    done
    echo ""
    echo "  Apps that import a missing package will fail to load."
    echo "  Once the network is back, restart the add-on from its page."
    echo "─────────────────────────────────────────────────────────"
}

# Usage: uv_with_log <timeout_seconds> <log_file> <uv args...>
# Runs uv with a timeout, its output streamed to the container log and copied to log_file (/dev/null to keep no
# copy). Exits with uv's code, 124 on timeout: the script-wide pipefail makes the pipeline report it, not tee's.
uv_with_log() {
    local timeout_secs="$1" log_file="$2"
    shift 2
    timeout "${timeout_secs}" uv "$@" 2>&1 | tee "${log_file}"
}

# Set once a step's online attempt fails to connect (add-on only), so later steps go straight to --offline instead
# of each waiting out the same network failure.
INDEX_UNREACHABLE=0

# Usage: run_uv_offline <timeout_seconds> <label> <uv args...>
# The add-on's fallback: the step again with --offline, from the persisted uv cache. On failure, records label in
# SKIPPED_INSTALLS and returns 1.
run_uv_offline() {
    local timeout_secs="$1" label="$2"
    shift 2
    local exit_code=0
    wait_interruptibly uv_with_log "${timeout_secs}" /dev/null "$@" --offline || exit_code=$?
    if [ "${exit_code}" -eq 0 ]; then
        echo "Installed from the uv cache."
        return 0
    fi
    echo "WARNING: the offline install failed too (exit ${exit_code}); continuing without ${label}"
    SKIPPED_INSTALLS+=("${label}")
    return 1
}

# ── helper: run a uv install step, with an offline fallback under the add-on ──
# Usage: run_uv_install <timeout_seconds> <failure_type> <label> <uv args...>
# failure_type: see print_install_failure_banner for the valid set
# label: what the step installs, named in the degraded-start banner
# Returns 0 on success. Under the add-on, a timeout or a connection failure retries the step with --offline; if that
# fails too, the step is recorded for the degraded-start banner and it returns 1, so the caller can skip what depends
# on it. Every other failure halts, so 1 always means "skipped".
run_uv_install() {
    local timeout_secs="$1" failure_type="$2" label="$3"
    shift 3

    if [ "${INDEX_UNREACHABLE}" -eq 1 ]; then
        echo "The package index was unreachable earlier; installing from the uv cache (--offline)"
        run_uv_offline "${timeout_secs}" "${label}" "$@"
        return
    fi

    local exit_code=0 network_failure=0
    # || halt: this runs where set -e is off (callers use `|| return 0` / `|| true`), and tee into an empty path
    # would fail a successful install
    uv_log_file=$(mktemp "${TMP_ROOT}/uv-log.XXXXXX") || halt 1 "couldn't create a temp file in ${TMP_ROOT}" "${REMEDY_UNEXPECTED}"
    wait_interruptibly uv_with_log "${timeout_secs}" "${uv_log_file}" "$@" || exit_code=$?
    if [ "${exit_code}" -ne 0 ]; then
        if [ "${exit_code}" -eq 124 ] || grep -qE "${UV_NETWORK_ERROR_PATTERN}" "${uv_log_file}"; then
            network_failure=1
        fi
    fi
    rm -f "${uv_log_file}"
    uv_log_file=""

    if [ "${exit_code}" -eq 0 ]; then
        return 0
    fi

    if [ "${network_failure}" -eq 1 ] && [ "${RUNTIME}" = "addon" ]; then
        INDEX_UNREACHABLE=1
        echo "WARNING: couldn't reach the package index (exit ${exit_code}); retrying from the uv cache (--offline)"
        run_uv_offline "${timeout_secs}" "${label}" "$@"
        return
    fi

    if [ "${exit_code}" -eq 124 ]; then
        echo "ERROR: dependency install timed out after ${timeout_secs}s"
        halt 1 "the dependency install timed out" "${REMEDY_NETWORK}"
    fi
    if [ "${network_failure}" -eq 1 ]; then
        echo "ERROR: dependency install couldn't reach the package index (exit ${exit_code})"
        halt 1 "the package index couldn't be reached (see above)" "${REMEDY_NETWORK}"
    fi

    print_install_failure_banner "${failure_type}"
    echo "ERROR: dependency install failed (exit ${exit_code})"
    halt 1 "a dependency conflict (see above)" "${REMEDY_DEPS}"
}

# ── helper: pip-install user requirements without breaking hassette ─────────
# Usage: run_uv_pip_install_guarded <timeout_seconds> <failure_type> <label> <pip install args...>
# The constraints file only bounds packages the user asks for, so hassette's exact pin is also
# passed as a requirement: that pulls hassette's full dependency tree (pydantic, hassette-wire, ...)
# into the resolution, and a user pin that would downgrade any of it fails as a conflict. uv
# resolves the pin from the already-installed hassette, so the image's version needn't be on PyPI.
# Returns what run_uv_install returns.
run_uv_pip_install_guarded() {
    local timeout_secs="$1" failure_type="$2" label="$3"
    shift 3

    run_uv_install "${timeout_secs}" "${failure_type}" "${label}" pip install "$@" \
        -c "$CONSTRAINTS" \
        "${HASSETTE_REQUIREMENT}"
}

HASSETTE_REQUIREMENT=$(grep -m1 '^hassette==' "$CONSTRAINTS" || true)
if [ -z "${HASSETTE_REQUIREMENT}" ]; then
    echo "ERROR: $CONSTRAINTS has no hassette== pin."
    halt 1 "the image's constraints file is incomplete" "${REMEDY_IMAGE}"
fi

# ---------------------------------------------------------------------------
# 1. Project-based install (export deps → install with constraints → install package)
# ---------------------------------------------------------------------------
# A step skipped by a failed offline install (run_uv_install returns 1) ends the project install, since each later
# step needs the one before it. `|| return 0`, not `|| return`: the skip is already recorded in SKIPPED_INSTALLS, and
# a non-zero return here would end the script under set -e.
install_project() {
    local label="your project (${PROJECT_DIR}/uv.lock)"
    user_deps_file=$(mktemp "${TMP_ROOT}/user-deps.XXXXXX")
    tmp_project=$(mktemp -d "${TMP_ROOT}/project-build.XXXXXX")

    log_phase "project install: exporting locked deps"
    run_uv_install "$UV_EXPORT_TIMEOUT_SECS" "export" "${label}" export \
        --no-hashes --frozen \
        --directory "$PROJECT_DIR" \
        --no-default-groups \
        --no-dev --no-editable --no-emit-project \
        --output-file "${user_deps_file}" || return 0

    log_phase "project install: installing deps with constraints"
    run_uv_pip_install_guarded "$UV_PROJECT_DEPS_TIMEOUT_SECS" "project" "${label}" -r "${user_deps_file}" || return 0

    log_phase "project install: installing project package"
    tar -C "$PROJECT_DIR" "${PROJECT_COPY_EXCLUDES[@]/#/--exclude=}" -cf - . | tar -C "$tmp_project" -xf -
    run_uv_install "$UV_PROJECT_PACKAGE_TIMEOUT_SECS" "project" "${label}" pip install \
        --no-deps "$tmp_project" || return 0

    log_phase "project install: complete"
}

if [ -f "$PROJECT_DIR/uv.lock" ]; then
    log_phase "project install: starting (from $PROJECT_DIR)"
    install_project
    # Explicit cleanup — the EXIT trap never fires on the happy path because
    # the script ends in `exec`, which replaces the shell process instead of exiting it.
    cleanup_tmp
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
            # a skipped file (failed offline retry) is recorded for the banner; the other files still install
            run_uv_pip_install_guarded "$UV_REQUIREMENTS_TIMEOUT_SECS" "requirements" "${req}" -r "$req" || true
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

if [ "${#SKIPPED_INSTALLS[@]}" -gt 0 ]; then
    print_degraded_start_banner
fi

log_phase "handing off to hassette"
exec hassette run "$@"

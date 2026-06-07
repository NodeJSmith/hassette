---
topic: "docker restart loop prevention on unrecoverable startup errors"
date: 2026-06-07
status: Draft
---

# Prior Art: Docker Restart Loop Prevention

## The Problem

hassette's Docker entrypoint already detects dependency conflicts at startup (via a constraints file that pins hassette and all transitive deps). When a consumer's lock file pins an incompatible version, the entrypoint prints a clear `DEPENDENCY CONFLICT` banner and exits non-zero.

The problem is what happens next. Under Docker's `restart: unless-stopped` (which hassette recommends), the container restarts immediately. Same conflict. Same exit. The container loops forever, burning resources and filling logs with repeated error messages. The user has to notice via `docker logs`, SSH in, and fix the lock file manually.

Docker has no mechanism for a container to say "don't restart me." No crash-loop detection. No max-retry on `unless-stopped`. The "start on boot, don't loop on errors" policy is [moby/moby#49397](https://github.com/moby/moby/issues/49397) — still open.

This research covers three angles: version coordination patterns (how frameworks prevent the mismatch), self-hosted dependency installation patterns (what's acceptable at container startup), and restart loop prevention (how to stop the loop when an unrecoverable error is detected).

## How We Do It Today

hassette's Docker image builds from source via `uv sync --locked --no-editable`. At build time, `generate_constraints.py` creates `/app/constraints.txt` containing all declared dependency ranges plus an exact `hassette==<version>` pin. At startup, `docker_start.sh` installs the consumer's project dependencies with `pip install -r <exported-deps> -c $CONSTRAINTS`. If any dependency conflicts with the constraints (including a hassette version mismatch), pip fails and the entrypoint prints a contextual error banner with remediation instructions.

The detection and messaging work. The container just won't stop restarting.

## Patterns Found

### Pattern 1: Halt-on-Init-Failure (Recommended)

**Used by**: LinuxServer.io (hundreds of containers)

**How it works**: During container initialization, if any step fails (permissions, config validation, dependency check), the init process halts but does not exit. The container stays alive in an idle state — s6-overlay keeps PID 1 running, but the application never starts. Docker sees the container as "running" and restart policies never trigger.

LinuxServer.io explicitly chose this over `exit 1` because restart loops cause "weird resource spikes" and "running through the init steps over and over" is wasteful and masks the original error under noise. Their init scripts have checkpoints at each stage, and any failure at any checkpoint stops the entire sequence.

**Strengths**: No restart loop. Logs stay clean (one error message, not hundreds). No resource churn. Works under any restart policy. The simplest effective solution.

**Weaknesses**: The container appears "running" to monitoring tools, which could mask the failure. Requires the user to check `docker logs` or use a healthcheck to discover the problem.

**Source**: https://www.linuxserver.io/blog/how-is-container-formed

### Pattern 2: Recovery/Safe Mode (Serve an Error Page)

**Used by**: Home Assistant

**How it works**: When HA detects a configuration problem during startup, instead of crashing, it loads a minimal set of system integrations — just enough to serve the web frontend, display logs, and allow the user to fix the config through the browser. The container stays alive and the web UI is accessible.

HA distinguishes two degraded modes:
- **Recovery mode** (automatic): triggered by startup failures. Loads only frontend, backup, and cloud integrations.
- **Safe mode** (manual): triggered by user action. Loads Core without custom integrations.

**Strengths**: The user discovers the problem in the browser, not via SSH + `docker logs`. No restart loop. The user can fix the problem through the UI.

**Weaknesses**: More complex to implement. Can itself fail on severe errors. Requires the application to have a web UI (hassette does).

**Source**: https://www.home-assistant.io/integrations/recovery_mode/

### Pattern 3: Exit-1 and Loop (Anti-Pattern)

**Used by**: Nextcloud, PostgreSQL, MySQL, most self-hosted applications

**How it works**: The entrypoint validates preconditions. On failure, it prints an error and calls `exit 1`. Under `restart: unless-stopped`, this creates an infinite restart loop.

**Why it's the worst option**: Nextcloud is the cautionary tale. Its entrypoint rsyncs files *before* the version check, so each restart attempt further corrupts the data directory. Users report being stuck in restart loops where even reverting the image doesn't help because the data is now in an inconsistent state ([nextcloud/docker#2207](https://github.com/nextcloud/docker/issues/2207), [#1129](https://github.com/nextcloud/docker/issues/1129)).

hassette's current behavior falls into this pattern, though without the destructive-work-before-validation problem (the constraints check runs before any state changes).

**Source**: https://github.com/nextcloud/docker/blob/master/docker-entrypoint.sh

### Pattern 4: Consumer-Side Automation (Prevention)

**Used by**: Any project using Renovate or Dependabot with uv

**How it works**: The consumer configures Renovate (preferred for uv projects) or Dependabot to watch for hassette releases on PyPI. When a new version is published, the bot opens a PR that updates both `pyproject.toml` and `uv.lock`. CI runs; if tests pass, the consumer merges and redeploys.

Renovate has native uv.lock support and `lockFileMaintenance` for periodic transitive dep refreshes. Dependabot has uv.lock support as of late 2025.

**Strengths**: Prevents the mismatch from ever reaching production. CI catches breaking changes before deploy.

**Weaknesses**: Requires the consumer to set up the bot. Doesn't help with the immediate deploy-time mismatch if the consumer hasn't merged yet. A prevention measure, not a runtime fix.

**Source**: https://docs.astral.sh/uv/guides/integration/renovate/

### Pattern 5: Version-Pinned Docker Image Tags (Prevention)

**Used by**: Dagster, Prefect, most Docker-distributed frameworks

**How it works**: The framework publishes version-tagged images (`hassette:0.40.0-py3.13`). Documentation tells consumers to pin both the image tag and the package version in lockstep. Floating tags (`latest`, `main-py3.13`) are discouraged for production.

hassette already publishes version-tagged images. The gap is documentation: the deployment docs don't connect the dots between image tag and lock file coordination, and hautomate was using the floating `main-py3.13` tag.

**Strengths**: Makes upgrades intentional and atomic. Easy to roll back.

**Weaknesses**: Manual coordination. Floating tags are more convenient and users default to them.

**Source**: https://docs.dagster.io/deployment/oss/deployment-options/docker

## Self-Hosted Ecosystem Context

The enterprise Docker community says "never install deps at startup." The self-hosted community draws a different line:

**Acceptable at startup**: database migrations, permission fixes, config generation, downloading data files, installing *user-provided* extension dependencies.

**Not acceptable at startup**: installing the application's own core dependencies, running `pip install -e .` for the project itself.

Key precedents:
- **AppDaemon** installs user requirements.txt at every container start. This is documented, first-class, and accepted. But AppDaemon has no protection against users overriding AppDaemon itself via requirements ([AppDaemon#844](https://github.com/AppDaemon/appdaemon/issues/844) — user's unpinned `appdaemon` requirement pulled a breaking major version).
- **Home Assistant Core** pip-installs integration dependencies at runtime from `manifest.json`. Works most of the time but generates recurring bug reports on Python version upgrades.
- **LinuxServer.io** provides `INSTALL_PIP_PACKAGES` as an official mechanism but acknowledged the startup performance cost was bad enough to build a caching infrastructure (Modcache/Modmanager).
- **Airflow** recommends users pin `apache-airflow` at the image's version in their requirements to prevent silent version swaps. Documentation-only enforcement.

hassette's constraints file already solves the AppDaemon#844 problem — it prevents users from overriding hassette or its transitive deps to incompatible versions.

## Docker Engine Limitations

| Capability | Status |
|---|---|
| Container signals "don't restart me" | Not possible |
| Max retries on `unless-stopped` | Not supported (only on `on-failure`) |
| Healthcheck-driven restart | Not supported (metadata only) |
| Crash-loop detection | Not supported (Kubernetes has `CrashLoopBackOff`; Docker has nothing) |
| "Start on boot only" policy | Open request ([moby/moby#49397](https://github.com/moby/moby/issues/49397)) |
| Configurable backoff | Not supported ([moby/moby#41856](https://github.com/moby/moby/issues/41856)) |
| Exponential backoff cap | 60 seconds, not configurable. Resets after 10s uptime. |

## Anti-Patterns

- **Floating tags with pinned lock files**: `main-py3.13` auto-advances the image while the lock file stays pinned. Direct cause of the hautomate boot loop.

- **Destructive work before validation**: Nextcloud rsyncs files before checking version compatibility. Each restart attempt worsens the corruption. hassette correctly validates constraints before any state changes.

- **Silent version mismatches**: Dagster's gRPC version drift surfaces as mysterious "UNAVAILABLE" errors. hassette's constraints file makes conflicts explicit with clear remediation instructions.

## Recommendation

**Two layers, framework-side and consumer-side:**

### Framework-side: halt instead of exit (Pattern 1)

When `docker_start.sh` detects a dependency conflict (or any other unrecoverable startup error), instead of `exit 1`:

1. Print the existing conflict banner (already implemented)
2. Optionally start a minimal health endpoint that returns the error details at `/api/health/live` (so monitoring tools and autoheal can distinguish "idle due to error" from "healthy")
3. `sleep infinity` — container stays alive, Docker doesn't restart it, logs are clean

This is the LinuxServer.io pattern and the strongest solution. It works under any restart policy, requires no consumer-side setup, and turns a restart loop into a single clear error message.

### Consumer-side: prevention through automation (Patterns 4 + 5)

Document in the Docker deployment guide:
- Recommend version-pinned image tags for production deployments
- Provide a sample `renovate.json` for automated lock file updates
- Document `uv lock --upgrade-package hassette` as the manual upgrade command
- Warn about the floating-tag + pinned-lock-file mismatch

## Sources

### Reference implementations
- https://github.com/nextcloud/docker/issues/2207 — Nextcloud restart loop on failed upgrade
- https://github.com/nextcloud/docker/issues/1129 — Nextcloud destructive entrypoint + version check ordering
- https://github.com/AppDaemon/appdaemon/issues/844 — AppDaemon user requirements overriding framework version
- https://github.com/dagster-io/dagster/issues/32091 — Dagster version mismatch failure mode
- https://github.com/docker-library/python/issues/355 — Rejected entrypoint install proposal
- https://github.com/home-assistant/core/issues/166255 — HA runtime pip install failure on Python upgrade

### Docker engine issues
- https://github.com/moby/moby/issues/49397 — Request for "start on boot only" restart policy
- https://github.com/moby/moby/issues/41856 — Request for configurable backoff
- https://github.com/moby/moby/issues/42873 — Backoff cap at 60 seconds (undocumented)

### Documentation & guides
- https://www.linuxserver.io/blog/how-is-container-formed — LinuxServer halt-on-init-failure pattern
- https://www.home-assistant.io/integrations/recovery_mode/ — HA recovery mode
- https://docs.docker.com/engine/containers/start-containers-automatically/ — Docker restart policies
- https://docs.astral.sh/uv/guides/integration/renovate/ — uv + Renovate
- https://docs.astral.sh/uv/guides/integration/dependabot/ — uv + Dependabot
- https://docs.dagster.io/deployment/oss/deployment-options/docker — Dagster Docker deployment
- https://docs.astral.sh/uv/guides/integration/docker/ — uv Docker guide
- https://hynek.me/articles/docker-uv/ — Production Python Docker with uv

### Blog posts & community
- https://browniebroke.com/blog/2024-10-02-keep-uv-lock-file-up-to-date-with-dependabot-updates/ — Dependabot uv.lock workaround
- https://jdhao.github.io/2026/05/13/uv_lock_file_management_with_renovate/ — Renovate + uv.lock
- https://last9.io/blog/docker-status-unhealthy-how-to-fix-it/ — Healthcheck and restart policy interaction

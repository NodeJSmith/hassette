---
topic: "runtime dependency installation in containerized Python frameworks"
date: 2026-04-03
status: Draft
---

# Prior Art: Runtime Dependency Installation in Containerized Python Frameworks

## The Problem

Containerized Python frameworks that run user-supplied code face a tension: users need to install their own dependencies (the packages their automations/DAGs/apps depend on), but the framework needs to protect its own packages from being downgraded or corrupted by those user dependencies. The question is where and how to install user packages — at image build time, at container startup, or not at all — and what guardrails prevent a user's `requests>=1.0` from pulling in a transitive dependency that downgrades the framework itself.

This is especially acute for home automation frameworks where users are often non-developers who expect "drop a file in a folder and it works."

## How We Do It Today

Hassette uses the AppDaemon pattern (Pattern 1 below): the startup script discovers `requirements*.txt` files via `fd`, installs them with `uv pip install -r`, then re-installs hassette from source (`uv pip install /app`) as a "version protection" step. This last step is always-true dead code (the guard condition can never be false), bypasses the lockfile, adds startup latency, and does not actually prevent transitive dependency conflicts — pip/uv's resolver may have already resolved a conflicting version during the user install step.

## Patterns Found

### Pattern 1: Entrypoint File Discovery (AppDaemon)

**Used by**: AppDaemon, Hassette (current), many generic containerized Python tools
**How it works**: At container startup, the entrypoint script recursively walks mounted directories for `requirements.txt` files and runs `pip install -r` for each. No version conflict checking is performed — packages install into the same site-packages as the framework.

**Strengths**: Zero friction for users; convention-driven; works for any pip-compatible package.
**Weaknesses**: No protection against framework downgrade; reinstalls on every startup (latency + network dependency); user can include the framework itself at a different version and silently downgrade it; pip errors crash startup even for non-critical packages.
**Example**: https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html

### Pattern 2: Constraints File Enforcement (Apache Airflow / AWS MWAA)

**Used by**: Apache Airflow, AWS MWAA, Airflow's official Docker image extension guidance
**How it works**: The framework publishes a version-specific `constraints.txt` with every release, listing exact resolved versions of all transitive dependencies. This file is baked into the Docker image. User package installs must pass `-c constraints.txt`, which causes pip to **error** (not silently downgrade) if user requirements conflict with the framework's dependency tree. Airflow also instructs users to pin the framework itself in the install command: `pip install my-package apache-airflow==X.Y.Z`.

AWS MWAA enforces this server-side — users upload a `requirements.txt` and MWAA applies constraints automatically.

**Strengths**: Explicit, documented protection; pip errors loudly on conflict; constraints file is version-pinned per release; managed-service variant removes user error entirely.
**Weaknesses**: Constraints file must stay in sync with each release; per-invocation only (a second pip call without `-c` is unprotected); can over-constrain legitimate user packages.
**Example**: https://airflow.apache.org/docs/apache-airflow/stable/installation/installing-from-pypi.html

### Pattern 3: Hermetic Build-Time Baking (Prefect)

**Used by**: Prefect (recommended), any framework favoring immutable infrastructure
**How it works**: All dependencies — framework and user — are installed at image build time. The running container makes no network calls and has no pip. Users who need new packages rebuild the image via `FROM framework:version RUN pip install my-deps`.

**Strengths**: Fully reproducible; no startup latency; no runtime network dependency; conflicts surfaced at build time, not at 2am; immutable artifacts simplify rollback.
**Weaknesses**: Requires CI/CD for every dependency change; poor DX for rapid iteration; cannot support varying user deps without per-user image builds.
**Example**: https://github.com/PrefectHQ/prefect/discussions/4042

### Pattern 4: Namespaced Install into `deps/` Directory (Home Assistant Core)

**Used by**: Home Assistant Core (for integration requirements)
**How it works**: Integration dependencies are installed into a `deps/` subdirectory via `pip install --target /config/deps`. Python's `sys.path` is manipulated to make this directory importable. Framework packages live in the venv's site-packages, physically separate from user packages.

**Strengths**: Filesystem isolation prevents direct overwrite; integration deps persist across restarts; one integration's failure doesn't affect others.
**Weaknesses**: Shared import namespace — `sys.path` ordering determines which version wins; `--target` installs don't enforce constraints against the primary venv; potential for stale deps on downgrade.
**Example**: https://developers.home-assistant.io/docs/creating_integration_manifest/

### Pattern 5: Separate Virtualenv per Layer (Hynek Schlawack)

**Used by**: Recommended in blog posts; used in some multi-tenant Python frameworks
**How it works**: Framework installs into `/app/.venv` at build time. User requirements install into `/app/user.venv` at runtime. Both are on `sys.path`, with the framework venv first — so framework packages always win import resolution regardless of what the user installed.

**Strengths**: True filesystem isolation; import precedence provides runtime protection; user venv can be recreated without touching the framework.
**Weaknesses**: More complex entrypoint; two venvs use more disk; `sys.path` ordering must be explicitly managed; entry points and console scripts may resolve incorrectly.
**Example**: https://hynek.me/articles/docker-virtualenv/

### Pattern 6: Config-Driven Package List (HA Community Add-on)

**Used by**: Home Assistant Community AppDaemon add-on, other HA add-ons
**How it works**: Users declare packages in YAML config (exposed in the HA UI). The entrypoint reads the list and runs `pip install` for each package name. Schema-validated input prevents injection of pip flags.

**Strengths**: Better UX for non-technical users; schema validation; visible in add-on config.
**Weaknesses**: No constraints; no conflict detection; same self-downgrade risk as Pattern 1.
**Example**: https://github.com/hassio-addons/app-appdaemon/blob/main/appdaemon/DOCS.md

## Anti-Patterns

- **Unconditional `pip install` with no pin or constraint**: The default AppDaemon and current Hassette behavior. User packages can silently downgrade the framework. (Source: AppDaemon docs — absence of constraint documentation)
- **Reinstalling all requirements on every startup**: Adds 10–60s latency, requires network access, causes non-deterministic failures when PyPI is unavailable. (Source: AppDaemon, Prefect discussion)
- **Constraints are per-invocation, not persistent**: Passing `-c constraints.txt` to one `pip install` does not protect subsequent invocations. Entrypoint scripts running multiple pip steps need constraints on every one. (Source: https://luminousmen.com/post/pip-constraints-files/)
- **Re-installing the framework from source as "version protection"**: Hassette's current `uv pip install /app` step. This runs after user deps are installed, so the resolver has already made its choices — reinstalling the framework may fix the framework version but leave its transitive dependencies in the state the user's install resolved to, creating a broken but not obviously broken environment.

## Emerging Trends

- **uv replacing pip in framework entrypoints**: AppDaemon's build stage already uses uv; the runtime entrypoint for user deps has not migrated yet. `uv pip install` is significantly faster and supports the same constraints/requirements file formats.
- **Managed environments enforcing constraints server-side**: AWS MWAA enforces constraints on every user `requirements.txt` without user opt-in. For self-hosted frameworks, the equivalent is the entrypoint always appending the framework's constraints file.

## Relevance to Us

Hassette currently uses Pattern 1 (AppDaemon-style file discovery) with a broken version of Pattern 2's "re-pin the framework" step. The challenge findings identified this as the root cause of 5 separate issues.

**What maps well to Hassette's context:**
- **Constraints file (Pattern 2)** is the lowest-friction fix for the self-downgrade problem. Hassette already uses `uv` and `uv.lock` — generating a constraints file from the lockfile at image build time is a one-line addition to the Dockerfile. The entrypoint then passes `-c /app/constraints.txt` to every `uv pip install` call.
- **Hermetic build-time baking (Pattern 3)** is already documented in Hassette's `dependencies.md` as the "pre-building a custom image" pattern. Making it the recommended default (instead of runtime install) aligns with the challenge findings.
- **Separate venv (Pattern 5)** would provide the strongest isolation but adds complexity that may not be justified for Hassette's user base.

**What doesn't fit:**
- **Namespaced `deps/` directory (Pattern 4)** works for HA Core because integrations are loaded by the framework; Hassette apps are user Python files that import packages normally, so `--target` + `sys.path` manipulation would be a surprising deviation.
- **Config-driven package list (Pattern 6)** is designed for the HA add-on UI context; Hassette's Docker users already manage their own files.

## Recommendation

**Combine Patterns 2 + 3 as a two-tier approach:**

1. **Default path (hermetic)**: Document the `FROM hassette:X.Y.Z RUN uv pip install ...` pattern as the primary, recommended way to add user dependencies. No runtime pip install. This is already partially documented but not positioned as the default.

2. **Opt-in runtime install with constraints**: For users who need runtime file-discovery install (the current behavior), gate it behind `HASSETTE__INSTALL_DEPS=1` and **always** pass a constraints file generated from the lockfile at build time: `uv pip install -r "$req" -c /app/constraints.txt`. This prevents framework downgrade while preserving the convenience path.

3. **Remove `uv pip install /app`**: The current "version protection" step is ineffective and adds latency. The constraints file replaces it correctly.

This maps directly to challenge findings 4, 8, and 12 — and the constraints file approach is battle-tested by Airflow (the most mature open-source example of this exact problem).

## Sources

### Reference implementations
- https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html — AppDaemon Docker tutorial (file discovery pattern)
- https://github.com/AppDaemon/appdaemon/blob/dev/Dockerfile — AppDaemon Dockerfile (uv build stage)
- https://github.com/hassio-addons/app-appdaemon/blob/main/appdaemon/DOCS.md — HA Community AppDaemon add-on (config-driven pattern)
- https://developers.home-assistant.io/docs/creating_integration_manifest/ — HA Core integration manifest (namespaced deps)
- https://hacs-pyscript.readthedocs.io/en/latest/reference.html — Pyscript reference (no-install pattern)

### Blog posts & writeups
- https://hynek.me/articles/docker-virtualenv/ — Why I Still Use Python Virtual Environments in Docker
- https://hynek.me/articles/docker-uv/ — Production-ready Python Docker Containers with uv
- https://luminousmen.com/post/pip-constraints-files/ — Pip Constraints Files explained
- https://www.pythontutorials.net/blog/can-i-prevent-pip-from-downgrading-packages-implicitly/ — Preventing implicit pip downgrade

### Documentation & standards
- https://airflow.apache.org/docs/apache-airflow/stable/installation/installing-from-pypi.html — Airflow installation with constraints
- https://airflow.apache.org/docs/docker-stack/build.html — Airflow Docker image extension
- https://docs.aws.amazon.com/mwaa/latest/userguide/working-dags-dependencies.html — AWS MWAA dependency installation
- https://pip.pypa.io/en/stable/topics/dependency-resolution/ — pip dependency resolution behavior
- https://docs.astral.sh/uv/pip/compatibility/ — uv pip compatibility notes
- https://github.com/PrefectHQ/prefect/discussions/4042 — Prefect deployment patterns

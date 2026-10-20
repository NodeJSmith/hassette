---
topic: "CLI that works in both a lightweight client install and the full framework install"
date: 2026-10-20
status: Draft
---

# Prior Art: One CLI Across a Client Package and a Framework Package

## The Problem

Issue #2387 moves the `hassette` CLI into `hassette-client[cli]`, so `pip install hassette-client[cli]` gives a working `hassette` that queries a remote server without the framework or web stack. `pip install hassette` must keep every command, including `hassette run` and local target discovery, which plug in from the framework. Five questions are open: which package declares the console script, how the framework adds commands, where constants both sides need live, where app-instance name lookup lives, and how commands drive the async client.

None of the declared HA-ecosystem peers has this shape. AppDaemon ships one package with one local `appdaemon` script; no remote CLI was found for pyscript, NetDaemon or HA core. Node-RED is the only exception: `node-red-admin` is a separate remote-admin CLI over its HTTP API, also bundled into the server. The useful precedents are outside the ecosystem.

## How We Do It Today

- The `hassette` script lives in the root package (`pyproject.toml:135-136` → `hassette.__main__:entrypoint`), and `src/hassette/cli/__init__.py:96-126` wires every command statically, `run` included.
- `pyproject.toml:70-71` already pins `hassette-client[cli]`; `client/pyproject.toml:35-36` has an empty `cli = []` extra waiting for this work.
- The CLI's HTTP client (`src/hassette/cli/client.py`) uses httpx2; `hassette-client` uses aiohttp.
- `TOKEN_FILENAME` (`src/hassette/web/auth/tokens.py:21`) is reached by the CLI only through `web_api_token_path`, called from `src/hassette/cli/target.py:342` during local discovery, which reads `HassetteConfig`.
- App-instance name resolution (`_find_by_name`, `resolve_instance*`, `client.py:371-460`) is pure HTTP lookup plus usage errors.
- `design/specs/114-hassette-client/brief.md:174-210` already proposes: one script owned by `hassette-client`, an ImportError install hint without `[cli]`, a `hassette.cli` entry point with `register(app)` that warns and continues on load failure, and remote targets in `~/.config/hassette/cli.toml`.

## Patterns Found

### Pattern 1 (script placement): Server owns the script, client has no CLI

**Used by**: Prefect (`prefect` script in `prefect`; `prefect-client` declares none and its PyPI page lists the CLI as a known limitation), AppDaemon, Datasette.
**How it works**: The full package declares `[project.scripts]`; the client is SDK-only. Anyone wanting the CLI installs the framework.
**Strengths**: Simplest packaging; no collisions.
**Weaknesses**: Fails #2387's goal outright. This is the "they don't bother" answer, and it's the most common one.
**Example**: https://raw.githubusercontent.com/PrefectHQ/prefect/main/client/pyproject.toml

### Pattern 2 (script placement): Light base package owns the script, extra supplies deps, ImportError hint

**Used by**: FastAPI (base `fastapi` declares the script, guards `import fastapi_cli`, prints "install `fastapi[standard]`"), Black (`blackd` always installed, `[d]` supplies aiohttp).
**How it works**: Extras can't gate `[project.scripts]` (PyPA spec), so the base package always installs the script. Its entry function imports the extra-only dependency inside a try/except and prints how to install it when missing.
**Strengths**: One package, one command name, works in every install. Maps directly onto `hassette-client` owning `hassette`.
**Weaknesses**: Bare `pip install hassette-client` gets a script that errors on use; the guard must run before cyclopts is imported. Only one distribution may declare the script name, so the root `hassette` package must drop its own declaration.
**Example**: https://raw.githubusercontent.com/fastapi/fastapi/master/fastapi/cli.py

### Pattern 3 (script placement): Separate remote-CLI distribution with its own name

**Used by**: Airflow (AIP-94 moves remote commands to `apache-airflow-ctl` → `airflowctl`; local/admin commands stay in `airflow`), Dagster (`dagster-graphql`), Node-RED (`node-red-admin`), Temporal (Go binary).
**How it works**: The remote CLI is its own installable with its own command name; the server keeps local commands under its own CLI.
**Strengths**: Exact dependencies, clean ownership. Airflow's motivation matches ours: API as the single source of truth, no CLI paths that bypass it.
**Weaknesses**: Two command names; Airflow carries a deprecation period with remote commands in both CLIs. Doesn't give one `hassette` command everywhere.
**Example**: https://cwiki.apache.org/confluence/spaces/AIRFLOW/pages/382175838/AIP-94+Decouple+Remote+Commands+from+airflow+CLI+to+airflowctl

### Pattern 4 (adding commands): In-process entry-point group

**Used by**: Flask (`flask.commands`), MLflow (`mlflow.app`, `mlflow.deployments`), llm and Datasette (pluggy), pytest (`pytest11`).
**How it works**: The owning CLI iterates `importlib.metadata.entry_points(group=...)` and loads each one; the heavier package declares an entry point, so its commands exist only when it's installed. "Both installed" works by construction.
**Strengths**: Installing the package is the whole registration step; shared parser, help and global flags.
**Weaknesses**: Flask doesn't wrap `ep.load()`, so one broken plugin breaks every command including `--help`, and failed loads retry on every call. llm adds an `LLM_LOAD_PLUGINS` env var as an escape hatch. Startup cost scales with installed distributions (use `importlib.metadata`, never `pkg_resources`). No source states a command-name collision policy or handles stale entry points.
**Example**: https://raw.githubusercontent.com/pallets/flask/main/src/flask/cli.py

### Pattern 5 (adding commands): Subcommand executables on PATH

**Used by**: Jupyter (`jupyter-*`), git, kubectl plugins.
**How it works**: The root command finds `<prog>-<name>` on PATH and execs it.
**Strengths**: A broken subcommand can't take down the root.
**Weaknesses**: A process per command, no shared help, global flags re-parsed everywhere. Poor fit for a cyclopts app with a meta launcher.
**Example**: https://raw.githubusercontent.com/jupyter/jupyter_core/main/jupyter_core/command.py

### Pattern 6 (shared constants): Generated models or hand-mirrored lists

**Used by**: Airflow (`airflowctl` generates models from core's OpenAPI spec, no import of core), Prefect (client dependency list mirrored by hand with a "keep in sync" comment).
**How it works**: Either derive the client's view from the server's contract or duplicate it and police the copy. No source describes a dedicated shared package like `hassette-wire` holding constants.

### Pattern 7 (target resolution): Profiles/contexts in the config layer, CLI edits them

**Used by**: Prefect (`profiles.toml` is a layer in settings precedence; `prefect profile` edits it), kubectl (`--context` then `current-context`), Ray (`RAY_ADDRESS`), node-red-admin (`target`, `login`).
**How it works**: A name maps to URL plus credentials in a user-level file; resolution is flag, then env var, then file default.
**Relevance**: This is about choosing a *server*, which the brief already covers with `cli.toml` + `--target`. No source speaks to resolving names *within* a server (our app-instance lookup).

### Pattern 8 (async): Async SDK, CLI accepts coroutine commands

**Used by**: Prefect (async-default client with a sync option; `with_cli_exception_handling` wraps coroutine commands). Where Prefect actually runs the coroutine wasn't retrieved.
**Relevance**: Thin evidence. Nothing found argues against one `asyncio.run` per command for short request/response commands.

## Anti-Patterns

- Unwrapped entry-point loading in the root CLI (Flask): one bad plugin breaks `--help`.
- Depending on `click-plugins`: deprecated; its README says to vendor the file.
- Entry-point extras syntax (`blackd = "...:main [d]"`): legacy, and the script installs regardless.
- A "client" that still pulls the web stack: both `prefect-client` and `mlflow-skinny` list fastapi/starlette/uvicorn. `hassette-client` is already lighter than either.

## Relevance to Us

**Q1, script placement.** The brief's plan is Pattern 2, and FastAPI is a close precedent. Its one hard consequence: the root `hassette` package must stop declaring the `hassette` script and rely on `hassette-client[cli]` to provide it, because two distributions declaring one script name is undocumented territory (only MLflow does it, and only because both share one module tree). Pattern 3 (a separate `hassette-ctl`-style name) is what Airflow, Dagster and Node-RED chose, but it breaks the milestone's "one `hassette` command" done-when, so it's only worth revisiting if Pattern 2 hits a wall.

**Q2, adding commands.** The brief's `hassette.cli` entry point with warn-and-continue is Pattern 4 with Flask's main pitfall already designed out. Hassette has exactly one known plugin, so pluggy, an env-var escape hatch, or a collision framework would all be more machinery than any peer uses for a single first-party plugin. One gap remains for the sketch: what happens when the plugin registers a name the client already owns. No peer documents a policy; an error at registration is the cheapest honest answer.

**Q3, shared constants.** The question may not need answering. The CLI reaches `TOKEN_FILENAME` only through `web_api_token_path` during local discovery (`target.py:342`), and local discovery stays in the framework plugin. The client side gets tokens from `cli.toml` for remote targets. If that holds in the sketch, `TOKEN_FILENAME` stays where it is and the leaf-module extraction the issue proposes (which would violate the brief's "nothing in hassette imports hassette_client" rule) goes away. If a client-only install does need to read a local token file, prior art offers only duplication or generation; putting a filename in `hassette-wire` would stretch its "types that cross the wire" charter.

**Q4, app-instance lookup.** Prior art covers server targets, not lookup within a server. The lookup is pure HTTP, so it can move into the client package; whether it lives on `HassetteClient` (SDK users get it) or in the CLI layer (SDK stays index-only) is a sketch decision with no external precedent either way.

**Q5, async.** One `asyncio.run` per command fits every current command, since none streams or pages. The real decision is the HTTP library: the CLI uses httpx2 and `hassette-client` uses aiohttp. Porting onto `HassetteClient` drops httpx2 from the CLI path.

## Recommendation

Keep the brief's direction; prior art supports it rather than overturning it.

- Script: Pattern 2 (FastAPI model). `hassette-client` declares `hassette`; the root package drops its declaration.
- Commands: Pattern 4 with each entry-point load wrapped, warn and continue. No pluggy, no env-var escape hatch, error on a name collision.
- Constants: confirm in the sketch that only the framework plugin needs `TOKEN_FILENAME`; if so, don't move it.
- Async: `asyncio.run` per command on `HassetteClient`; retire httpx2 from the CLI.

Coverage gaps: most pyproject claims were read through a summarizing fetch rather than raw; Dagster's own packaging files 404'd; no source covers entry-point name collisions or stale entry points; Prefect's async bridge wasn't located.

## Sources

URLs were not live-verified.

### Reference implementations
- https://raw.githubusercontent.com/PrefectHQ/prefect/main/pyproject.toml — `prefect` script in the full package
- https://raw.githubusercontent.com/PrefectHQ/prefect/main/client/pyproject.toml — `prefect-client`, no scripts
- https://raw.githubusercontent.com/PrefectHQ/prefect/main/src/prefect/cli/_utilities.py — CLI wrapper accepting coroutine commands
- https://raw.githubusercontent.com/mlflow/mlflow/master/pyproject.toml — `mlflow` script and plugin entry-point groups
- https://raw.githubusercontent.com/mlflow/mlflow/master/libs/skinny/pyproject.toml — `mlflow-skinny` declaring the same script
- https://raw.githubusercontent.com/apache/airflow/main/airflow-ctl/pyproject.toml — `airflowctl`, httpx-based, no core dependency
- https://raw.githubusercontent.com/fastapi/fastapi/master/fastapi/cli.py — base-package script with ImportError install hint
- https://raw.githubusercontent.com/psf/black/main/pyproject.toml — `blackd` script with `[d]` extra
- https://raw.githubusercontent.com/pallets/flask/main/src/flask/cli.py — `flask.commands` entry-point loading
- https://raw.githubusercontent.com/simonw/llm/main/llm/plugins.py — pluggy plus `LLM_LOAD_PLUGINS`
- https://raw.githubusercontent.com/jupyter/jupyter_core/main/jupyter_core/command.py — PATH subcommand discovery
- https://raw.githubusercontent.com/simonw/datasette/main/pyproject.toml — single package, single script
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/pyproject.toml — peer: single package, local script
- https://github.com/node-red/node-red-admin — peer: separate remote-admin CLI
- https://github.com/click-contrib/click-plugins — deprecated entry-point helper

### Blog posts & writeups
- https://airflow.apache.org/blog/airflowctl-0.1.0 — airflowctl announcement
- https://lists.openstack.org/pipermail/openstack-discuss/2020-July/015806.html — entry-point scan cost, `pkg_resources` vs `importlib.metadata`

### Documentation & standards
- https://packaging.python.org/en/latest/specifications/pyproject-toml/ — scripts are unconditional
- https://cwiki.apache.org/confluence/spaces/AIRFLOW/pages/382175838/AIP-94+Decouple+Remote+Commands+from+airflow+CLI+to+airflowctl — remote/local CLI split rationale
- https://pypi.org/project/prefect-client/2.20.14 — CLI listed as a known limitation
- https://docs.prefect.io/v3/concepts/settings-and-profiles — profiles in the settings layer
- https://docs.prefect.io/v3/manage/interact-with-api — async-default client with sync option
- https://docs.ray.io/en/latest/cluster/running-applications/job-submission/quickstart.html — `RAY_ADDRESS` targeting
- https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/ — context resolution order
- https://tessl.io/registry/tessl/pypi-dagster-graphql/1.11.0/files/docs/cli.md — `dagster-graphql` CLI (unofficial)

---
topic: "User App and Plugin Definition Patterns"
date: 2026-05-01
status: Draft
---

# Prior Art: User App and Plugin Definition Patterns

## The Problem

Automation frameworks need users to write extensible units of code — apps, plugins, integrations — that the framework can discover, configure, instantiate, and manage. The design choices determine the user's authoring experience (how much boilerplate?), the framework's control (can it restart a failed app? run multiple instances?), and the ecosystem's extensibility (can third parties publish reusable apps?).

The problem has several interacting dimensions: **definition** (how does a user declare an app — base class, decorator, function?), **configuration** (how does typed config bind to an app instance?), **discovery** (how does the framework find apps — manifests, file scanning, entry points?), **lifecycle** (what hooks does the app get — initialize, ready, shutdown?), **multi-instance** (can the same app class run with different configs?), and **resource isolation** (does each app get its own bus, scheduler, logger?). Frameworks that get these right enable a thriving ecosystem; frameworks that don't become monolithic applications with no extension story.

## How We Do It Today

Hassette uses **`App[AppConfig]` — a generic base class parameterized by a typed Pydantic config class**. Apps are discovered via `hassette.toml` manifests (filename, class_name, app_dir, config) with optional auto-detection (recursive filesystem scan for `App` subclasses). The config type is extracted from `__orig_bases__` automatically — no manual class variable needed. Each app instance gets four injected resources: Bus, Scheduler, Api, and StateManager as children in the Resource tree. Lifecycle hooks follow a six-phase pattern: `before_initialize` → `on_initialize` → `after_initialize` → `before_shutdown` → `on_shutdown` → `after_shutdown`, with `AppSync` wrapping async to sync. Multi-instance is supported via list/dict-based `app_config` in the manifest. Errors during class load, config validation, and initialization are caught and recorded per-app without blocking others.

## Patterns Found

### Pattern 1: Base Class Inheritance with External Config

**Used by**: AppDaemon, hassette, Celery (Task), older Airflow DAGs

**How it works**: Users subclass a framework-provided base class and override lifecycle methods. Configuration is external — YAML (AppDaemon's `apps.yaml`), TOML (hassette), or env vars. The framework discovers classes by scanning modules, then instantiates them with associated config. The base class provides access to framework services as instance attributes. Multi-instance is natural: same class appears multiple times in config with different parameters.

In more sophisticated variants, the config is a typed object — a Pydantic `BaseSettings` subclass (hassette) or Django's `AppConfig`. Hassette's `App[MyConfig]` generic is the most type-safe version found, where the config type flows through as a generic parameter.

**Strengths**: Familiar OOP pattern. IDE autocompletion on base class methods. Natural home for lifecycle hooks. Multi-instance trivial. Typed config generics catch misconfiguration at startup.

**Weaknesses**: Tight coupling to framework base class (hard to test without the framework). Single inheritance limits composition. Base class can become a "god object."

**Example**: https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html

### Pattern 2: Manifest-Based Discovery with Lifecycle Entry Points

**Used by**: Home Assistant integrations, VS Code extensions, Node-RED nodes, Gradle plugins

**How it works**: Each plugin ships a manifest file (`manifest.json`, `package.json`) declaring metadata (name, version, dependencies, capabilities) separately from code. The framework scans manifests to discover plugins, then calls well-known entry points (`async_setup_entry()`, `activate()`) to initialize them. VS Code takes this furthest with "contribution points" — static JSON declarations of menus, commands, views that the host processes without loading extension code.

HA adds a config-entry layer: each integration can have multiple config entries (e.g., two Hue bridges), and `async_setup_entry` is called per entry. The `hass` object provides shared services.

**Strengths**: Clean metadata/code separation. Enables lazy loading (read manifest without importing code). Framework validates dependencies before loading. Rich tooling (marketplace, dependency graphs). Human-readable manifests.

**Weaknesses**: Manifest and code can drift. Two artifacts to maintain. JSON/YAML can't express complex constraints. Manifest schema becomes a versioned API surface.

**Example**: https://developers.home-assistant.io/docs/creating_integration_manifest/ / https://code.visualstudio.com/api/get-started/extension-anatomy

### Pattern 3: Hook-Based Composition (Pluggy)

**Used by**: pytest, tox, devpi, Jupyter

**How it works**: The host declares hook specifications (`@hookspec` functions). Plugins provide implementations (`@hookimpl` matching the spec's signature). A `PluginManager` collects implementations and calls them 1:N when the host invokes a hook. Discovery at three levels: builtin, entry_points, and filesystem convention (conftest.py). Multiple plugins can implement the same hook; results are aggregated. Ordering via `tryfirst`/`trylast`.

**Strengths**: No base class — plugins are plain modules with decorated functions. Composition over inheritance. Multiple plugins extend the same point. Clean host API / plugin behavior separation. Proven at pytest scale.

**Weaknesses**: Higher conceptual overhead. Hook spec API is hard to change once published. Debugging execution order is opaque. No natural home for per-plugin state or config.

**Example**: https://docs.pytest.org/en/stable/how-to/writing_plugins.html

### Pattern 4: Decorator-Based Registration

**Used by**: Airflow (`@dag`, `@task`), Flask (`@app.route`), FastAPI (`@app.get`), Celery (`@app.task`)

**How it works**: Decorators on functions or classes register them with the framework. Metadata (name, schedule, route) is captured by the decorator. Airflow's TaskFlow API infers task dependencies from Python function calls. FastAPI adds `Depends()` for signature-based DI. Since Airflow 2.4, decorated DAGs auto-register without module-level globals.

**Strengths**: Minimal boilerplate. No base class. Works with plain functions (better testability). Inline configuration via decorator args. IDE decorator support is good.

**Weaknesses**: Magic — registration side effects not obvious. Discovery requires importing the module (no lazy loading). Complex per-instance config doesn't fit decorator args well.

**Example**: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html

### Pattern 5: Entry Points (setuptools / importlib.metadata)

**Used by**: stevedore (OpenStack), pytest (external plugins), pip, black, mypy, flake8

**How it works**: Plugins register via `entry_points` in `pyproject.toml`. The host uses `importlib.metadata.entry_points(group="myapp.plugins")` or stevedore's managers to discover plugins. Registration at install time (not import time) — the host enumerates plugins without importing code. Stevedore provides four manager patterns: DriverManager (single), NamedExtensionManager (named subset), EnabledExtensionManager (filtered), DispatchExtensionManager (routed).

**Strengths**: Standard Python mechanism. Install-time registration. Plugins are independently installable packages. No filesystem scanning. Ecosystem-native.

**Weaknesses**: Requires packaging step. Development friction (`pip install -e .`). Global namespace collisions. No built-in lifecycle or config support.

**Example**: https://docs.openstack.org/stevedore/latest/user/essays/pycon2013.html

### Pattern 6: File-Based Convention Discovery

**Used by**: Airflow (DAGs directory), Django (models.py, admin.py), pytest (conftest.py), Celery (tasks.py)

**How it works**: The framework scans a directory for files matching a naming convention. Airflow scans for `.py` files containing "airflow" and "dag" strings. Django imports `models.py` from each installed app. Convention often layers atop another mechanism: Django's within `INSTALLED_APPS`, pytest's conftest alongside entry_points.

**Strengths**: Zero-configuration. No packaging step. Intuitive for beginners. Supports gradual adoption.

**Weaknesses**: Fragile (renamed files break discovery). Requires importing all discovered modules at startup. No metadata without parsing. Can be slow for large codebases.

**Example**: https://docs.djangoproject.com/en/5.2/ref/applications/

### Pattern 7: Scoped Dependency Injection with Per-Plugin Resources

**Used by**: Backstage, VS Code (ExtensionContext), .NET plugin systems, hassette

**How it works**: The framework creates an isolated resource scope per plugin. Backstage has two tiers: root-scoped (shared singletons) and plugin-scoped (per-plugin instances created by factories receiving plugin ID). VS Code gives each extension an `ExtensionContext` with per-extension storage, subscriptions, and secrets. .NET combines `AssemblyLoadContext` (code isolation) with DI child scopes (service isolation).

Hassette follows this pattern: each App gets its own Bus, Scheduler, Api, and StateManager. The Resource hierarchy with priority-based initialization ensures deterministic startup order.

**Strengths**: Strong isolation prevents cross-plugin interference. Per-plugin logging/metrics. Clean resource cleanup on shutdown. Easier testing (inject mocks per-plugin). Prevents global state.

**Weaknesses**: Higher memory overhead (N service instances vs 1). Cross-plugin communication requires explicit mechanisms. Scope boundary design is critical.

**Example**: https://backstage.io/docs/backend-system/architecture/services/ / https://backstage.io/docs/backend-system/architecture/plugins/

## Anti-Patterns

- **God base class**: The base class accumulates every service as methods/attributes. AppDaemon's `hass.Hass` trends this direction (state, scheduling, logging, service calls, UI rendering on one object). Changes affect every plugin's API. Better: inject services individually or provide as separate resources (hassette's approach). ([source](https://docs.openstack.org/stevedore/latest/user/essays/pycon2013.html))

- **Import-everything discovery**: Importing every `.py` in a directory to find plugins executes module-level side effects, causes slow startup, and means one import error can crash all discovery. Airflow added a string heuristic (`DAG_DISCOVERY_SAFE_MODE`) to mitigate this. Better: manifests, entry_points, or lightweight heuristic scan. ([source](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html))

- **Config-code drift**: External manifests diverge from code. A manifest declares a capability the code doesn't implement. Better: generate manifests from code (FastAPI → OpenAPI), or validate manifests against code at build time (HA's hassfest). Hassette's `App[Config]` generic eliminates config-type drift by making it a type parameter. ([source](https://developers.home-assistant.io/docs/creating_integration_manifest/))

- **Implicit singleton state**: Module-level globals make multi-instance impossible and tests leak. Flask migrated from globals to the factory pattern specifically to fix this. Better: multi-instance by default from day one — hassette and AppDaemon both do this well. ([source](https://flask.palletsprojects.com/en/stable/patterns/appfactories/))

## Emerging Trends

**Declarative-first with imperative escape hatches**: VS Code, Backstage, and HA move toward static metadata (JSON manifests, contribution points) with code only for runtime behavior. Enables tooling (marketplace, dependency analysis) without executing plugin code.

**Typed configuration as first-class**: Plugins declaring config schema as typed objects (Pydantic models, TypeScript interfaces, Gradle typed extensions) rather than dicts. Catches misconfiguration at startup, enables IDE autocompletion. Hassette's `App[Config]` and Gradle's `Extension` objects are leading examples.

**Function-level granularity**: Airflow's TaskFlow, FastAPI's `Depends`, Celery's `@task` — function-first approaches reduce boilerplate. Class-based retains advantages for lifecycle management and per-instance state.

**Per-plugin service scoping as standard**: Backstage's two-tier model (root singletons + plugin-scoped instances) is becoming the expected baseline. Hassette's per-app resource hierarchy follows the same principle.

## Relevance to Us

Hassette's app system is **well-designed and ahead of most comparable frameworks**:

**What we're doing well:**

- **`App[AppConfig]` generic** is the most type-safe version of Pattern 1 found across all surveyed frameworks. The config type extracted from `__orig_bases__` automatically — no manual class variable. Gradle's typed extensions are the closest analog outside Python.

- **Per-app resource isolation** (Pattern 7) — each app gets Bus, Scheduler, Api, StateManager. This matches Backstage's plugin-scoped services and VS Code's ExtensionContext, which are considered best-in-class for isolation.

- **Multi-instance by default** — same class with different configs via manifest, avoiding the singleton anti-pattern that Flask and many older frameworks had to retrofit.

- **Error isolation at three levels** — class load, config validation, initialization. Failures recorded per-app without blocking others. More robust than AppDaemon (which can hang on a blocking `terminate()`).

- **Six-phase lifecycle** — before/on/after for both initialize and shutdown gives apps fine-grained control. More structured than AppDaemon's two-hook model (initialize/terminate).

- **Thin base class** — services are injected as separate Resource children, not methods on a god class. This avoids the AppDaemon anti-pattern.

**Gaps worth examining:**

1. **No lazy activation**: All declared apps load at startup regardless of whether they'll be used. VS Code's activation-event pattern (load extension only when a relevant trigger fires) would be useful if hassette ever supports a large number of optional apps. Currently not needed for the typical home-automation use case (5-20 apps).

2. **No entry_points support for third-party apps**: Discovery is TOML manifests + filesystem scanning. For a future ecosystem of reusable apps (HACS-style), entry_points (Pattern 5) would let users `pip install hassette-app-presence` and have it discovered automatically. This is an ecosystem maturity concern, not a current need.

3. **TOML manifest is config-coupled**: The manifest (`hassette.toml [apps]`) combines discovery metadata (filename, class_name) with instance config. HA's pattern separates these: `manifest.json` for discovery, config entries for instance configuration. Separating them would enable listing available apps without loading their config, which matters for a future app-management UI.

4. **Auto-detection imports everything**: When `autodetect_apps` is enabled, hassette recursively scans and imports all `.py` files. This is the "import-everything" anti-pattern for large app directories. A lightweight heuristic (Airflow's string check) or manifest-based detection would be safer.

## Recommendation

Hassette's app system is the strongest in the HA Python ecosystem. The `App[AppConfig]` generic, per-app resource isolation, multi-instance support, and thin base class are all validated by the prior art as best-in-class choices.

No structural changes are needed. The gaps (lazy activation, entry_points, manifest separation) are ecosystem-maturity concerns that matter when hassette has a third-party app ecosystem, not today. The one near-term improvement worth considering is **guarding auto-detection** — if the feature is used, a lightweight pre-scan (checking for `App` or `AppSync` in file contents before importing) would prevent the import-everything anti-pattern without changing the user experience.

## Sources

### Reference implementations
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon app guide
- https://developers.home-assistant.io/docs/creating_integration_manifest/ — HA integration manifest
- https://github.com/home-assistant/home-assistant-js-websocket/blob/master/lib/connection.ts — HA JS client
- https://code.visualstudio.com/api/get-started/extension-anatomy — VS Code extension anatomy
- https://backstage.io/docs/backend-system/architecture/services/ — Backstage service scoping
- https://backstage.io/docs/backend-system/architecture/plugins/ — Backstage plugin architecture
- https://docs.gradle.org/current/userguide/implementing_gradle_plugins.html — Gradle typed plugins

### Blog posts & writeups
- https://sedimental.org/plugin_systems.html — Plugin system design decisions
- https://docs.openstack.org/stevedore/latest/user/essays/pycon2013.html — Stevedore plugin taxonomy
- https://medium.com/@garzia.luke/developing-plugin-architecture-with-pluggy-8eb7bdba3303 — Pluggy architecture
- https://jnsgr.uk/2024/10/writing-a-home-assistant-integration/ — HA integration walkthrough
- https://dev.to/autonomousapps/gradle-plugins-and-extensions-a-primer-for-the-bemused-51lp — Gradle extensions
- https://waylonwalker.com/python-pluggable-architecture/ — Python plugin pattern comparison
- https://www.devleader.ca/2026/04/12/building-a-vs-codestyle-extension-system-in-c — VS Code model in C#
- https://nikhilakki.in/understanding-djangos-auto-discovery-a-deep-dive — Django auto-discovery
- https://chinghwayu.com/2021/11/how-to-create-a-python-plugin-system-with-stevedore/ — Stevedore tutorial

### Documentation & standards
- https://code.visualstudio.com/api/references/activation-events — VS Code activation events
- https://code.visualstudio.com/api/references/extension-manifest — VS Code manifest
- https://docs.pytest.org/en/stable/how-to/writing_plugins.html — pytest plugin guide
- https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html — Airflow DAG discovery
- https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html — Celery auto-discover
- https://docs.djangoproject.com/en/5.2/ref/applications/ — Django applications
- https://flask.palletsprojects.com/en/stable/patterns/appfactories/ — Flask app factory
- https://nodered.org/docs/creating-nodes/first-node — Node-RED custom nodes
- https://github.com/home-assistant/architecture/blob/master/adr/0007-integration-config-yaml-structure.md — HA ADR-0007

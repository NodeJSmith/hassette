# Design: Log Identity Axes

**Date:** 2026-10-18
**Status:** ratified
**Mode:** sketch
**Issues:** #2496, #3044, #3046, #462, #1689 (gap 3 only)

## Summary

Every log record has three independent properties:
- **Author:** did app code or framework code write the line?
- **Subject:** which app instance is it about?
- **Execution:** which handler or job run is it part of?

Execution already works. Author and subject are merged: the `source_tier` field reports author when a resource's logger stamps it. Otherwise it infers author from whether an `app_key` is bound, so framework lines about an app (lifecycle, executor errors) are tagged as the app's own. The console makes the reverse mistake. Trimming its key=value tail (#3044, closed PR #3052) assumed the logger name identifies the subject, and it doesn't: framework loggers log on behalf of apps, and default instance names collide across app keys.

This design separates the three axes for log records and settles everything that follows from them: how each is stamped, how an app's log level reaches framework lines about it, how identity renders on the console, and how the UI and CLI mark author. It also settles what an app instance's identity is (D5, D11), because the subject axis needs a stable, unique name to point at. Unique names ship first, as the opening issue of the logging work; re-keying storage, routes and the client on the name follows as its own milestone.

**Hard requirement:** a user debugging their app can see every line about it, including framework-authored ones, at the verbosity they chose, with author marked. What shows by default, and what takes an explicit opt-in, is D9's rule; raising framework verbosity is D4's. The one exception is shared services (CommandExecutor, AppLifecycleService): their lines about an app follow service levels, so per-app DEBUG from them isn't available (D4).

**Prior work:** the prior-art brief `2026-10-18-log-identity-axes` in `design/research` (peers: AppDaemon, HA core, pyscript, Prefect, Dagster, Celery, Temporal, Airflow, OTel). Earlier briefs: `2026-05-02-logging`, `2026-04-07-telemetry-tier-separation`.

**Where things live** (by concept, per the Altitude stance):
- **Instance identity:** one naming function in app config normalization (`hassette.config.classes`) does the defaulting (snake_case class name for auto-loaded apps) and the charset check. It is called by the `AppManifest` `app_config` validator and `model_post_init`, `AppFactory`, the `AppRegistry` fallback for instances without a live App, and the test harness's default manifest. Cross-config uniqueness is checked where every manifest is visible at once: the config-level manifest validation in `hassette.config.config` (D5, D11). Name-keyed rows, routes and lookups live in the existing telemetry repository and queries, the app registry and owner registries, the instance web routes and their wire models, `hassette-client`, the CLI instance resolver, and the frontend's instance URLs (D11).
- **Author and owner identity:** fixed on each logger object when its resource builds it, in `hassette.resources` (the successor to the per-resource tier filter in `hassette.resources.base`). An App passes its identity to its children and to its lifecycle logger (D1, D2, D3).
- **The identity resolver:** one small filter in `hassette.logging_`, attached to both output paths, the Phase 1 stream handler and the Phase 2 queue handler. It copies identity from the record's logger or its nearest identified ancestor, and applies D3's defaults when there is none. For `py.warnings` records it reads the author from the warning category and source module, which the warning capture hook in `hassette.logging_` attaches (D1). `CorrelationFilter` keeps the execution axis and stops inferring author.
- **The `author` record field:** carried on log records through the telemetry log table, the log wire models and the log API, and emitted by the JSON formatter in place of `source_tier` (D8).
- **Per-app verbosity:** ordinary logger levels, all set by one effective-level resolver in `hassette.resources` (D4). `AppConfig.log_level` sets the app's own logger. A new `AppConfig` field sets the app's framework-owned loggers (D4, D10). Shared framework services keep their `LoggingConfig` service levels.
- **The console identity column:** the console and compact formatter chains in `hassette.logging_` (D7).
- **The default author filter:** the shared log-record filter behind the log API's general and execution queries, in `hassette.core.telemetry`, applied when the API's `author` parameter is absent. It replaces the per-view tier defaults in the log query and the frontend log-filters hook, so every caller, `hassette-client` included, gets the same default (D9).
- **The author marker, opt-in and hidden-lines indicator:** the web log table component shared by every log view, which keeps the opt-in as viewer-local UI state and sends `author=all` when it is on, and the CLI `log` command (D9).

**Out of scope:**
- Service-status events. App-owned children reach framework status consumers; that is #2938, already in the *DB as Source of Truth* milestone. It is the same author/subject split on a different record type, so cross-link it and apply this model there.
- New log pages or views.
- Backfilling historical rows.
- The per-app level toggle UI (#345). It builds on D4 but is a feature, not part of either milestone's Done-when.
- #1689's two concurrency gaps (lock boundaries, timeout handling).

## Posture

- **Failure handling:** loud and minimal. A line with no subject has no subject; the only fallbacks are ones a decision adds. Invalid or duplicate instance names fail at config load with an error naming the sections involved.
- **Compatibility:** break freely, since we're pre-v1. Each break gets a changelog/migration note and, where the released `hassette-client` is affected, a `client_compat` ignore entry. Schema changes ship as a migration with no backfill; retention ages old rows out.
- **Scope:** the complete model for log records (the *Log identity* milestone): unique instance names, author, subject, execution, level reach, console, CLI and UI marking, and user docs, with unique names opening it (D5, D11's naming half); then re-keying storage, routes and the client on the name (D11; the *Instance identity* milestone). Service-status is cross-linked only. No new log views.
- **Rollout:** ship outright as several PRs per milestone, each landing green. No flags.
- **Hardening:** project defaults.
- **Altitude:** milestone. The issues may be picked up after files are split or moved, so everything is named by concept, module or class, never by path, line or code step.

## Decisions

### D1: How is a record's author determined?

**Deciding factor:** author can never be inferred from subject, and code the app brings counts as the app's.

| | A: By the writing logger | B: Author contextvar around user code | C: Stamp at each framework call site |
|---|---|---|---|
| Rule | Fixed per logger object at construction (see D3 for the mechanism). An app's own logger, and every logger outside the `hassette` tree (`extra_loggers`, libraries), is **app**. Every other `hassette.*` logger is **framework**: an app's Bus/Scheduler/Api/StateManager children, the app's lifecycle logger (D2), and framework services. A descendant of an identified logger (for example a user's `self.logger.getChild(...)`) takes its nearest identified ancestor's author | Any line emitted while user code (hooks, handlers, jobs) is on the stack is **app**; everything else is **framework** | Framework code passes an explicit author; the default is app |
| Framework lines inside a handler (Api calls, DI failures) | Correctly framework | Wrongly app, since user code is on the stack | Correct only where someone remembered the stamp |
| User module, library and sub-logger lines | App, by rule | App | App by default |
| Independent of subject | Yes; logger identity and bound context don't interact | Yes | Yes |
| New call sites stay correct | Automatically | Automatically | Only by discipline (Temporal's inconsistency) |
| Peer precedent | Celery, Temporal, Airflow 3, AppDaemon, HA | None found | None found |

One logger needs its own rule. `logging.captureWarnings(True)` routes every `warnings.warn` through the managed `py.warnings` logger: Hassette's own warnings (`HassetteForgottenAwaitWarning`, `HassetteBlockingIOWarning`, the `restart_spec` and migration warnings) as well as users' and libraries'. Its records take their author from the warning instead: framework when the warning's category is one of Hassette's classes or it was raised from a `hassette` module, app otherwise. The warning capture hook in `hassette.logging_` puts the category and source module on the record for the resolver. Making `py.warnings` always framework would hide users' own warnings by default (D9), and moving Hassette's warn sites onto loggers would lose Python's warning filters.

**Recommendation:** A, because it is the peer consensus and the only option that gets framework lines inside a handler right without per-call discipline.
**Pick B instead if** framework code routinely logs through loggers outside the `hassette` tree, which would make A's "outside the tree is app" rule wrong. **Pick C instead if** framework and app code must keep sharing one logger, which D2 decides.
**Reversibility:** easy (one rule, set at construction)
**Ratified:** Chose author-by-writing-logger, fixed on each logger object at construction with descendants taking their nearest identified ancestor's author, over an author contextvar or per-call stamps, so author is independent of subject and stays correct for new call sites, with captured warnings on `py.warnings` authored by their category or source module, accepting that framework code must log through `hassette.*` framework loggers (or `warnings.warn` from a `hassette` module) and a small hook on warning capture.

### D2: Which logger writes framework lines about an app?

Generic lifecycle code (`hassette.resources.lifecycle`, and the resource operation, service and task-bucket code that shares its logging) logs through the resource's own logger. For an app, that is the app's logger, so under D1-A those lines would count as app-authored.

**Deciding factor:** lifecycle lines are framework-authored and carry the app by construction, with no discipline at each call site.

| | A: Per-app lifecycle logger | B: One shared lifecycle logger, subject bound per call | C: Keep the resource logger, stamp author per call |
|---|---|---|---|
| Rule | Every resource exposes the logger that generic lifecycle code writes through. For non-app resources that is their own logger. Each App also gets one extra framework-authored logger, owned by the app, for lines the framework writes about it | Lifecycle code logs through one `hassette` lifecycle logger and binds the app at each call | Lifecycle code keeps `resource.logger` and passes `framework` at each call |
| Fits D1-A without call-site discipline | Yes | No | No |
| Extra loggers | One per App | One in total | None |
| Level control (D4) | The app's lifecycle logger takes `framework_log_level` directly | Needs a subject-aware gate | Lines follow the app's `log_level` |
| Peer precedent | AppDaemon and HA use framework loggers for these lines | AppDaemon (`_app_management`), HA (`config_entries`), with the subject in the message | None |

**Recommendation:** A, because it keeps "correct by construction" true and gives D4 a per-app logger to set a level on. CommandExecutor and AppLifecycleService already log through their own framework loggers and keep doing so; they take their subject from context (D3).
**Pick B instead if** you'd rather not add a logger per App and accept a subject bind at every lifecycle call site.
**Reversibility:** easy
**Ratified:** Chose a per-app framework-authored lifecycle logger (used by generic lifecycle code for Apps) over a shared lifecycle logger or per-call stamps, so lifecycle lines about an app are framework-authored and owned by the app by construction, accepting one extra logger per App and that these lines no longer follow the app's `log_level` but D4's resolution (`framework_log_level`, else `app_handler`; migration note).

### D3: How is subject stamped, and which source wins?

**Deciding factor:** every line about an app reaches that app's view, from the source that actually knows. The stamp must be the same in Phase 1 (sync console) and Phase 2 (queued pipeline).

| | A: Identity on the logger object, thin resolver on both handlers | B: Bound context plus owner lookup in the downstream pipeline | C: Context only (today) |
|---|---|---|---|
| Where identity is set | Once, when a resource builds its logger: author and owner (app key and instance name, plus `instance_index` while the log table still stores it, until issue 6 drops it; after that the index is display order only, per D11). An App passes its identity to its children and its lifecycle logger | Owner is looked up when each record is processed | Only contextvars around executions and lifecycle phases |
| Who reads it | One small filter on each output handler (the Phase 1 stream handler and the Phase 2 queue handler). It takes identity from the record's logger, or else from its nearest ancestor logger that carries identity. It walks logger objects, not name strings | `CorrelationFilter` on the queue handler only | `CorrelationFilter` |
| Precedence | The owner stamp wins whenever the logger has one. Bound context supplies the subject only for ownerless loggers (shared services such as CommandExecutor, user module loggers, libraries) | Context wins over the owner | n/a |
| Framework task that inherited an app's context | Owner (none) means the context applies, so it is a known gap only for ownerless loggers (accepted) | Wrong app as subject | Wrong app as subject |
| App children logging outside a context window | Carry the app | Carry the app | No subject |
| Phase 1 lines | Same identity as Phase 2 | No identity | Ambient context only |
| Raw `threading.Thread` | Owned loggers keep their subject; ownerless loggers have none (documented) | Same | Nothing |
| Per-record cost | An ancestor walk only for unidentified loggers | A lookup per record | None |

When neither the logger nor any ancestor carries identity, the resolver uses the D1 namespace rule: inside the `hassette` tree, including the `hassette` root logger itself, the author is framework; outside it (`extra_loggers`, libraries), the author is app. Either way the line has no owner, so its subject comes from bound context.

**Recommendation:** A, because the writing logger already knows its author and owner from construction (the existing per-resource filter is the precedent), it needs no name parsing or resource lookups in `hassette.logging_`, and both phases see the same identity.
**Pick B instead if** most framework lines about apps come from loggers no resource owns, so construction-time identity covers little.
**Reversibility:** easy
**Ratified:** Chose identity fixed on logger objects at construction, read by a thin ancestor-walking filter on both the Phase 1 and Phase 2 handlers with the owner stamp winning over bound context, over a downstream owner lookup or context only, so subject comes from the source that knows and is the same in both phases, accepting that ownerless loggers (shared services, user module loggers) still take their subject from bound context, including context inherited by spawned tasks, and that a new output path added outside those two handlers must attach the filter itself (a record factory would cover it automatically but runs for every record in the process).

### D4: How does an app's log level reach framework lines about it?

Under D2-A, framework lines leave the app's logger, so an app at DEBUG would lose the framework's DEBUG lines about it. Today it gets them by accident. #462 asks that an app's children follow the app's level.

stdlib checks a logger's level before it creates a record or runs any filter. A gate downstream therefore can't let through a line its logger already dropped, so per-app verbosity has to be a logger level.

**Deciding factor:** the hard requirement, "at the verbosity they chose", without everyday noise or per-record cost. Every level defaults to the global `log_level` (INFO), so the options differ only when an app is set more verbose. Developers often leave an app at DEBUG for their own output for weeks.

| | A: App level reaches framework lines | D: Per-app framework level on the app's framework loggers | B: Children inherit (#462 as filed) | C: Framework level only (AppDaemon) |
|---|---|---|---|---|
| Rule | The app's `log_level` also governs every framework line about it, which needs framework loggers opened and a per-record gate | A new per-app setting is the level of the app's framework-owned loggers: its Bus/Scheduler/Api/StateManager children and its lifecycle logger (D2). It defaults to the framework's level. `log_level` governs only the app's own logger | An app's children take the app's `log_level`. Lifecycle lines stay at framework levels | An app's level governs only its own logger. Users raise framework levels to see more |
| App at DEBUG, everyday run | Also gets every framework DEBUG line about it (#2496's complaint made permanent) | Its own lines only | Its own lines plus its children's | Its own lines only |
| "Is it Hassette?" debugging | Automatic | Raise one per-app setting | Children only; lifecycle lines missing | Raise framework levels process-wide |
| Shared services' lines about the app (CommandExecutor, AppLifecycleService) | Gated per app | Follow their service levels. Their lines about apps are ERROR/WARNING, so their loggers emit those at defaults (log views show the WARNING ones only with D9's opt-in). Their DEBUG lines about apps follow the service level, so per-app DEBUG from them is not available (accepted) | Follow service levels | Follow service levels |
| Hard requirement | Met | Met for everything the app owns. Shared services meet it at WARNING and above | Partly | Not met |
| #462 | Subsumed | Subsumed: children follow the new setting, which keeps them framework-authored (D1) | Resolved | Closed |
| Mechanism and cost | Per-record gate; framework loggers opened whenever any app is verbose | Ordinary logger levels; no gate; no cost when unset; the same in both phases | Logger levels | None |
| Peer precedent | Extends HA's fan-out by subject | HA's per-integration "enable debug logging" (a level on the owner's set of loggers) | HA's declared set | AppDaemon |

Every logger's level comes from one effective-level resolver, a function of config keyed by the logger's owner and author and applied when the logger's resource is constructed. The current per-class `config_log_level` overrides feed it rather than setting levels themselves. Precedence, highest first:
1. the owning app's setting: `log_level` for the app's own logger, `framework_log_level` for its framework-owned loggers;
2. the `LoggingConfig` field for that component: `bus_service`, `scheduler_service` and so on for an app's children, `app_handler` for an app's lifecycle logger, and `logging.apps` for an app's own logger;
3. the global `log_level`.

A runtime change through the `PUT /logs/level` route stays a later `setLevel` on that logger. Nothing stores it, so rebuilding the logger's resource (an app reload) resets it to the resolved level, as today. #345 adds persistence if it needs it.

When `framework_log_level` is unset, an app's children keep their service-field level, so their behavior is unchanged. Its lifecycle logger follows `app_handler`. That is a change: today lifecycle lines follow the app's `log_level`. It gets a migration note, and setting `app_handler = "DEBUG"` shows every app's lifecycle detail at once.

**Recommendation:** D, because it meets the hard requirement for everything the app owns with plain logger levels, keeps everyday DEBUG quiet, and the only gap (per-app DEBUG from shared services) is the AppDaemon/HA position for shared framework code.
**Pick A instead if** per-app DEBUG from shared services matters enough to pay for a per-record gate. **Pick B instead if** you'd rather add no config field and accept lifecycle lines staying at framework levels. **Pick C instead if** app authors should never see framework DEBUG output about their app.
**Reversibility:** easy (one config field and logger levels)
**Ratified:** Chose a per-app framework level applied as the logger level of the app's framework-owned loggers (children and lifecycle logger) over a per-record subject-aware gate, so a user can opt into Hassette's detail about their app with no everyday noise and no per-record cost, with every level resolved from config by one effective-level resolver in the stated precedence and runtime `PUT /logs/level` changes left as an unstored later `setLevel`, accepting one new `AppConfig` field, that a runtime level change is lost when the app reloads, that shared services' DEBUG lines about an app follow their service levels (documented), and that with the setting unset an app's lifecycle logger follows `app_handler` instead of the app's `log_level` (migration note).

### D5: How are instance names chosen?

Today the default is `ClassName.<index>`, so two config sections using the same class collide. They then share a logger name, `unique_name`, and owner-keyed registrations. Nothing checks for duplicates, whether within one app key or across app keys.

Observed usage: the real-user config in `~/source/hautomate/config/hassette.toml` sets `instance_name` on every app that autostarts. Single-instance apps mostly repeat the section key, and the one multi-instance app names each entry. Six dormant `autostart = false` lab sections set no name, and two of them share a class.

**Deciding factor:** every configured instance name is a string the user typed, under one rule with no shape-dependent cases, so "the name is the identity" (D11) holds literally.

| | A: `<display_name>.<index>` default | E: Required only where ambiguous (section key for single instances) | R: Every configured instance must set `instance_name` | B: Keep class name, plus validation |
|---|---|---|---|---|
| Single-instance configured app | `<section_key>.0` | The section key | Must set `instance_name` | `ClassName.0` |
| Multi-instance (list) entries | `<section_key>.<index>` | Must set `instance_name` | Must set `instance_name` | `ClassName.<index>` |
| A table vs a one-entry list | Same | Needs a shape rule (they look identical after normalization) | Same rule | Same |
| Auto-loaded app (autodetected, no manifest section) | `ClassName.0` | Class name | The class name in snake_case, to fit D11's charset (the only default left) | `ClassName.0` |
| Derived name colliding with a typed one | Possible | Possible (a section key vs another section's list entry) | Can't happen for configured apps | Possible |
| Turning a single instance into a list | Renames it | The first entry must now be named, which is a rename and so a new instance (D11) | No change | Renames it |
| Redundant typing | None | None | A section key and a name, often identical | None |
| Breaks existing configs | No; default names change | Unnamed lists fail at load | Every configured instance without `instance_name` fails at load, with an error naming the section | No |
| Matches observed usage | Partly | Partly | Mostly; the real-user config names every autostarting app, and its six dormant lab sections would need a name or removal | No |
| Peer precedent | None exactly | AppDaemon, pyscript (the section key is the name) | AppDaemon and pyscript, in spirit: every instance's name is typed | None |

Naming is one function, called everywhere an instance's name is computed (the call sites are listed under *Where things live*). The requirement, the charset and the uniqueness check cover every configured section, whether or not it autostarts or is enabled, so a clash is caught at load rather than when a dormant app is switched on. The function branches on whether the manifest was autodetected, not on whether a section has a `config` block: a configured section with no `config` still needs a name. For an autodetected app it returns the class name in snake_case (`MyApp` → `my_app`); issue 1 picks one conversion rule and pins acronyms and digits (`HTTPServerApp`, `MyApp2`, `BlockingIOLab`) with tests, since the result becomes a permanent key. A class name whose snake_case form fails D11's charset is a load error naming the class, like any other invalid name. Two auto-loaded apps whose classes share a name collide under D11's uniqueness rule. That is a load error naming both, and the user resolves it by configuring one of them with an `instance_name`. Uniqueness and charset rules, and what the name keys, are D11.

**Recommendation:** R, because it is the only option with a single rule, typed names everywhere, and no derived-vs-typed collision, and it matches how users already write config for the apps they run.
**Pick E instead if** saving the redundant line on single-instance apps matters more than one rule. **Pick A instead if** configs must keep loading with no names at all. **Pick B instead if** existing users' names should stay as they are.
**Reversibility:** hard (names land in stored rows and in user config)
**Ratified:** Chose requiring `instance_name` on every configured instance, including sections that don't autostart (with the snake_case class name as the only default, for auto-loaded apps), computed by one naming function, over section-key or generated defaults, so every configured identity is a string the user typed under one rule, accepting a load error for any configured instance without a name (dormant sections included) and one often-redundant line per single-instance app.

### D6: What happens to #740's opaque logger names?

**Deciding factor:** logger names stay readable labels, as in every peer.

**Recommendation:** keep logger names readable and derived from instance identity. Close #740 as won't-do, citing the brief. D4 makes level control independent of logger names, D3 makes subject independent of them, and D5 makes them unique, so #740's motivation is gone.
**Pick opaque names instead if** something besides attribution and levels turns out to depend on logger-name parsing and breaks under D5's renames.
**Reversibility:** easy
**Ratified:** Chose readable, identity-derived logger names over #740's opaque names, so logger names remain grep-able labels, accepting that #740 closes as won't-do.

### D7: What identity does a console line carry?

**Deciding factor:** one scannable identity token per human-read line. Structured context stays in JSON and the DB.

| | A: Identity column, no tail | B: Keep the tail, drop noise keys (#3044 as filed, fixed) |
|---|---|---|
| Identity shown | One column: the subject's instance name when a subject is bound, otherwise the logger name without its `hassette.` prefix. A framework line about an app also shows its author, so "Hassette's line about my app" is distinguishable from "my app's line" | The logger name, plus a tail filtered by rules |
| Framework lines about an app (executor errors) | Show the app | Must keep the identity keys conditionally, which is the rule PR #3052 got wrong |
| Execution correlation | A short execution id is shown when one is bound; other keys are omitted | Kept in the tail |
| Phone width (add-on) | Short | Still long |
| Relation to #3046 | The compact format becomes a timestamp/padding variant of the same column layout | #3046 stays a separate renderer |
| Peer precedent | AppDaemon, HA, Celery (identity switches when a task is in scope) | None found |

**Recommendation:** A. It is the shape every peer uses, and it removes the conditional-tail logic that broke #3052. The exact visual format of the column and the author marker is left to the issue. The add-on uses the compact variant by default, as #3046 already decided for the Supervisor log tab.
**Pick B instead if** console users rely on the key=value tail for grep or for ad hoc parsing that JSON output can't serve.
**Reversibility:** easy
**Ratified:** Chose a single identity column (subject or logger, author marker, short execution id) with no key=value tail over a filtered tail, so console lines are short and attribution can't be dropped by tail rules, accepting that ad hoc context lives only in JSON and the DB.

### D8: How are author and subject named on the wire, and does #739's rename happen?

`source_tier` already means **owner tier** on listener, job and stall rows, where it drives cleanup, reconciliation and the `active_*` views. An App's Bus registers listeners as `app` (its parent's tier), while its own log lines are framework-authored (D1). One `SourceTier` literal is shared by the wire models, the CLI and the client.

**Deciding factor:** one name per concept, with a visible break, and without a wide rename the model doesn't need.

| | A: Keep both names, redefine `source_tier` on logs as author | C: New log-only `author` field; `source_tier` stays owner tier | B: Rename now (`app_key` → `owner_key`, `source_tier` → `author`) |
|---|---|---|---|
| Log records | `source_tier` means author on logs and owner tier elsewhere | Log records carry `author` (app/framework) in place of `source_tier`; `app_key` holds an app subject or nothing | Accurate either way |
| `--source-tier app` on `hassette log` vs `hassette listener` | Contradictory sets for the same component | `hassette log` filters with `--author`; `--source-tier` keeps one meaning everywhere | Consistent |
| Visibility of the break | Silent: same name and values, new meaning | Loud: a new field and parameter on logs | Loud and wide |
| Registration tables | Untouched | Untouched | Renamed |
| Breaking surface | The meaning change only | One log-table column (migration, no backfill), the log wire models, the log API and query parameter, CLI `log`, the UI log filter | Every telemetry table, the wire models, the frontend, the CLI and the client |
| #739 | Closes (won't-do) | Closes (won't-do); `app_key` stays | Done |

**Recommendation:** C, because it gives each concept its own name and makes the break visible, at the cost of one log-only migration that the Posture already accepts.
**Pick A instead if** you want no wire or schema change and accept that `--source-tier` means different things on different commands. **Pick B instead if** you want the pre-v1 window spent on names consistent across registrations and logs.
**Reversibility:** hard (renames land in schema and wire)
**Ratified:** Chose a new log-only `author` field (with `source_tier` keeping its owner-tier meaning on registrations) over redefining `source_tier` on logs or a pre-v1 rename, so each concept has one name and the change is visible to readers and released clients, accepting one log-table migration with no backfill and that framework registration rows keep `__hassette__.X` in `app_key` (#739 closes as won't-do).

### D9: What do log views and the CLI show by default?

**Deciding factor:** one default rule on every page and command, so what a user sees never depends on which view they opened. Seeing Hassette's internals is a deliberate opt-in, the same shape as D4, but a framework failure is never hidden.

| | A: Per-view defaults (per-app/execution show all, global shows app) | U1: Hide framework-authored lines everywhere, one opt-in | U1F: U1 plus an ERROR floor | U2: Show everything everywhere, marked, one filter to hide |
|---|---|---|---|---|
| Same rule on every page and CLI command | No; the same line is visible in one view and hidden in another | Yes | Yes | Yes |
| Default screen | Depends on the page | Only lines the user's code wrote | Lines the user's code wrote, plus framework lines at ERROR and above (marked), in every log view (global, per-app, execution) and every `hassette log` invocation | User's lines plus Hassette's, marked |
| "Is it Hassette?" | Depends on the page | One author control, the same on every log view (remembered per viewer), and `hassette log --author all` | Same control | Already visible |
| Handler-error and start-failure log lines | Shown in per-app views | Hidden until opted in | Shown (ERROR) | Shown |
| Framework errors with no app subject (websocket, database, retention) | Hidden on the global view | Hidden until opted in | Shown | Shown |
| Fit with D4 (internals are opt-in) | Mixed | Same shape | Same shape: framework detail below ERROR is opt-in | Different shape |
| Peer precedent | None found | Temporal (framework records hidden by default) | Temporal for hiding; every peer surfaces errors | AppDaemon, HA, Dagster |

With the opt-in on, a view shows every line it selects, whatever its author: per-app views still select by subject, and framework-authored lines are marked.

With the opt-in off, the author control shows an indicator that framework lines are hidden, so a user who raised `framework_log_level` (D4) learns the second switch exists. The issue picks between a count and a static note. `hassette log` prints the same as a one-line footer.

The rule lives once, in the log API: with no `author` parameter it returns app-authored lines plus framework lines at ERROR and above, and `author=all` is the opt-in. `author=app` returns app-authored lines only and `author=framework` framework-authored lines only, with no floor; `--author` in the CLI takes the same values. One shared log-record filter applies it in both the general log query and the execution log query. The UI and CLI pass the parameter; they don't filter.

**Recommendation:** U1F, because it keeps one rule everywhere and D4's opt-in shape while never hiding a failure, Hassette's or the app's.
**Pick U1 instead if** framework errors without an app subject should stay off the Logs page by default. **Pick U2 instead if** all framework output belongs on screen by default. **Pick A instead if** different views genuinely serve different audiences.
**Reversibility:** easy
**Ratified:** Chose hiding framework-authored lines below ERROR by default in every log view and `hassette log`, with framework ERROR and above always shown and marked, and one author opt-in that is the same everywhere (remembered per viewer in the UI, `--author all` in the CLI) with a hidden-lines indicator beside it (a footer in the CLI), the default applied once in the log API when no `author` parameter is given rather than in each client, over per-view defaults, hiding all framework lines, or showing everything, so the rule never depends on the page and no failure is hidden, accepting that framework WARNING-level lines about an app (timeouts) need the opt-in to appear in log views.

### D10: What is D4's per-app framework-verbosity setting called?

**Deciding factor:** a user reading `hassette.toml` can tell it apart from `log_level` without opening the docs.

| | A: `framework_log_level` | B: `debug_framework` (bool) | C: `hassette_log_level` |
|---|---|---|---|
| Says what it governs | Framework lines, at a level | Framework lines, on/off only | Hassette's lines, but could read as a global setting |
| Matches existing level fields | Yes (same `LogLevel` type as `log_level`) | No; a new shape | Yes |
| Can express WARNING-only quieting | Yes | No | Yes |
| What #345's toggle drives | A level picker | A switch | A level picker |

**Recommendation:** A, because it pairs visibly with `log_level`, shares its type, and lets a user quiet the framework's lines about a noisy app as well as raise them.
**Pick B instead if** the only use you expect is "turn on DEBUG to investigate". **Pick C instead if** "framework" reads as jargon to app authors.
**Reversibility:** hard (a user config key)
**Ratified:** Chose `framework_log_level` (a `LogLevel`) over a boolean switch or `hassette_log_level`, so it reads as the pair of `log_level` and can quiet as well as raise, accepting "framework" as user-facing vocabulary.

### D11: What is an app instance's identity?

An instance has four identifiers, each derived separately, and nothing makes them agree:
- `(app_key, instance_index)` keys DB rows (listeners, jobs, executions, logs), web routes and the CLI. It is positional, so reordering or inserting a list entry moves history and URLs to a different instance.
- `instance_name` is what users write and see. It isn't validated as unique.
- `App.unique_name` is derived through a "starts with the class name?" rule with no `app_key`. It keys logger names, `owner_id` and the Bus/Scheduler owner registries, and it collides across sections (#1689's gap 3).
- The logger name inherits `unique_name`'s problems, and dots in names become fake logger hierarchy.

**Deciding factor:** one stable, user-chosen identity per instance, validated once, with every other key derived from it or replaced by it.

| | F1: The name is the identity, everywhere | F2: Name identity for naming only; keying by index stays | B: Keep the derivations, add checks |
|---|---|---|---|
| Identity | The instance name (D5's rules), unique across the whole config, in Home Assistant's object-id charset (below) | Same | Unchanged |
| `unique_name`, logger name, `owner_id` | Equal to, or derived directly from, the name. The class-prefix rule is deleted | Same | Unchanged, plus a `unique_name` uniqueness check |
| DB natural keys, routes, CLI `--instance`, registry | Keyed by name. `instance_index` is display order only | Still `(app_key, instance_index)` | Unchanged |
| Reordering or inserting list entries | Never moves history; renaming an entry makes a new instance | Still moves history | Still moves history |
| Selective-restart name-overlap detection (`app_lifecycle_changes`) | Deleted | Kept | Kept |
| #1689 gap 3 | Solved structurally | Solved | Detected only |
| Cost | Schema migration (no backfill), routes, wire, client, CLI, frontend, registry | Small | Small |
| Peer precedent | AppDaemon (the name is the key) | None | None |

**Charset:** a name starts with a lowercase letter, contains only lowercase letters, digits and `_`, doesn't end with `_`, and is at most 128 characters. That is Home Assistant's entity object-id rule, so a name works unchanged as an HA object id, device identifier, URL segment, logger name and CLI argument, and the HACS integration needs no mapping. It also keeps `-` out of names, which the integration's `{key}-{entity}` unique ids rely on as a separator. Every real-user name already fits. Considered and rejected: letters, digits, `_` and `-` (makes those unique ids ambiguous and needs slugifying for HA), and forbidding only dots (pushes escaping into routes, the client, the CLI and the integration).

**Recommendation:** F1. The logging work needs only the naming half (unique names, and `unique_name`, logger and `owner_id` derived from them), so that half opens the logging work and the re-keying of DB rows, registry, routes and client follows as its own *Instance identity* milestone. D1–D10 read those keys only through the log table's `instance_index` column, which owner stamps keep filling until the re-key drops it. It also gives *DB as Source of Truth* stable keys to build on.
**Pick F2 instead if** the migration should wait until another initiative touches those tables. **Pick B instead if** you want no identity change at all.
**Reversibility:** hard (schema keys, routes and user-facing URLs)
**Ratified:** Chose making the user-chosen instance name the sole identity (unique across the config, in Home Assistant's object-id charset so the HACS integration needs no mapping, `unique_name`/logger/`owner_id` derived from it, DB rows, routes, CLI and registry keyed by it, index demoted to display order), with the naming half opening the logging work and the re-keying delivered afterward as a separate *Instance identity* milestone, over naming-only or added checks, so positional identity and cross-section collisions become impossible, accepting a schema migration with no backfill, breaking instance routes, URLs and the client, and that renaming an instance starts a new history (the old rows age out), stated in the app-configuration docs. #1689's concurrency gaps stay outside it.

## Assumed

These describe the code as it is before this design's first issue.

- Per-app log views filter on the stored `app_key` column (and `instance_index` for an instance), and their tier filter defaults to "all"; the global view defaults to tier "app". Evidence: `get_log_records` in `hassette.core.telemetry.summary_queries`; the log-filters hook in the frontend log table.
- Execution views select log records by `execution_id`, independent of tier. Evidence: the execution-logs query in `summary_queries`.
- Subject for stdlib records comes only from structlog contextvars, bound by `CommandExecutor.bind_execution_context` and around initialize/shutdown in `app_lifecycle_instances`. The resource tier filter stamps only the tier, and only for records created on that exact logger, not propagated ones. Evidence: `CorrelationFilter` in `hassette.logging_`; `_ResourceContextFilter` in `hassette.resources.base`.
- Only the Phase 2 queue handler carries `CorrelationFilter`; the Phase 1 stream handler has none. Evidence: `enable_basic_logging` in `hassette.logging_`; `LoggingService`.
- stdlib drops a record whose level is below its logger's level before any filter runs. Evidence: `logging.Logger.isEnabledFor` (Python standard library).
- Per-resource levels resolve through `Resource.config_log_level`. App children (Bus, Scheduler) hardcode their service-level fields, and `LoggingConfig.app_handler` exists. Evidence: the `config_log_level` overrides on `Bus`, `Scheduler`, `App`; `LoggingConfig`.
- The default `instance_name` is filled in as `<class_name>.<index>` by `AppManifest`'s `app_config` validator, and no validator checks duplicates. `App.unique_name` adds the class name unless the instance name already starts with it. Evidence: `hassette.config.classes`; `App.unique_name`; the comment on duplicate instance names in `app_lifecycle_changes`.
- The log table has no natural key; each row stores `app_key`, `instance_name` and `instance_index` from bound context, beside `source_tier`. The blocking-event table stores the same pair. The listener and scheduled-job tables store only `app_key` and a non-null `instance_index`, which are part of their natural keys, and executions carry no instance columns. Evidence: the `log_records`, `listeners`, `scheduled_jobs` and `executions` tables in the SQL migrations, and `blocking_events` in its own migration.
- Telemetry natural keys and instance routes use `(app_key, instance_index)`. Evidence: the listener and scheduled-job natural-key indexes in the SQL migrations; the instance routes in the web apps routes.
- `source_tier` is the owner tier on listener, job and stall rows, where it drives cleanup, reconciliation and the `active_*` views, and it is also exposed on log records in JSON output, `LogEntryResponse`, and the CLI `log`, `app`, `job` and `listener` commands. Evidence: the `Resource.source_tier` ClassVar docstring; `SourceTier` in `hassette_wire`; `hassette.web.models`; `hassette.cli.commands`.
- `LoggingConfig` has `apps` and `app_handler` level fields, each defaulting to the global level. Evidence: `LoggingConfig` in `hassette.config.models`.
- Framework registration rows use the reserved `__hassette__` app key or a `__hassette__.<component>` key. Evidence: `FRAMEWORK_APP_KEY` and `FRAMEWORK_APP_KEY_PREFIX` in `hassette.types`.
- Users' non-`hassette` loggers reach the pipeline only when listed in `LoggingConfig.extra_loggers`. Evidence: `enable_basic_logging` in `hassette.logging_`.

## Breakdown

Two milestones, in order: *Log identity*, then *Instance identity*. Each issue's "After:" names what it reads. Issue 1 is the only input the logging work takes from instance identity, so it opens *Log identity*, and the re-keying (issues 6–8) follows as its own milestone. Under the repo's design-completeness rule, each issue ships its own docs and any frontend, CLI and schema changes in the same PR; there are no separate docs or UI follow-ups.

### Milestone: Log identity

**Done when:** every app instance has one user-chosen name, unique across the config, and logger names and owner identity derive from it. Every log record carries author, subject and execution independently, and author comes from the writing logger, never from subject. Every log view and `hassette log` apply D9's default. With one opt-in, the same everywhere, a user can see every line about their app at the app's chosen verbosity, with framework-authored lines marked, in the web UI and the CLI. The console shows each line's subject and author in its identity column.

1. **User-chosen, unique instance names**: every configured instance must set `instance_name`, and an auto-loaded app defaults to its class name in snake_case, via one naming function. Names are unique across the config and use D11's charset (HA's object-id rule), checked at config-level manifest validation. `unique_name`, logger names and `owner_id` derive directly from the name, and the class-prefix rule is deleted. DB rows, routes and the registry stay keyed by `(app_key, instance_index)` until the *Instance identity* milestone. Ships the migration note: configured instances without `instance_name` now fail at load, and because the old default `ClassName.<index>` isn't a valid name, cache keys and event-source comparisons built from a defaulted name change value. The `hassette.testing` harness builds its default manifest as an autodetected app, so a harness app's name becomes its snake_case class name unless the test sets `instance_name`; the migration note tells user test suites that relied on `ClassName.0`. Also an app-configuration docs update. Solves #1689's gap 3. Implements: D5, D11. After: none. Issue: #3095
2. **Identity on loggers**: author and owner are fixed on logger objects at construction, an App passes its identity to its children and its new lifecycle logger, and generic lifecycle code writes about Apps through that logger. The identity resolver runs on both output paths, with the owner winning over bound context and D3's no-identity defaults. Captured warnings on `py.warnings` take their author from the warning's category and source module. The app-key → tier inference is deleted. Until issue 3 lands, log records keep their `source_tier` field, populated from author. Until issue 4 lands, the lifecycle logger's level is `app_handler`; this issue ships the migration note that lifecycle lines no longer follow the app's `log_level`. The owner stamp includes `instance_index` so per-instance log views keep finding framework lines until issue 6. Rescopes #2496. Implements: D1, D2, D3. After: 1. Issue: #2496
3. **The `author` field, end to end**: log records carry `author` in place of `source_tier` through the log table (migration, no backfill), the JSON formatter, the log wire models and the log API's `author` parameter, whose absence applies D9's default in the shared log-record filter, replacing the per-view tier defaults, with regenerated schemas and frontend types. The web log views get the author marker, the framework ERROR floor, the single opt-in and its hidden-lines indicator, and `hassette log` gets `--author`, the same marker and the hidden-lines footer in place of `--source-tier`. Ships `client_compat` ignore entries for the removed log field, and the new user docs page "where do my app's logs go", covering the three axes, how to tell whether a problem is Hassette's or the app's, and the raw-thread and inherited-context limits for ownerless loggers. Implements: D8, D9. After: 2. Issue: #3096
4. **Per-app framework verbosity**: `framework_log_level` on `AppConfig` sets the level of the app's framework-owned loggers, through one effective-level resolver with D4's precedence and unset behavior. Documents that shared services' DEBUG lines about an app follow their service levels, and that `framework_log_level` now also sets the lifecycle logger. Updates the log-level and app-config docs and the generated schemas. Closes #462. Implements: D4, D10. After: 2. Issue: #3097
5. **Console identity column and compact format**: the key=value tail is replaced by the identity column (subject or logger, author marker, short execution id), and the compact format becomes its time-only, unpadded variant, made the add-on default. One log-format docs update. Rescopes #3044 and #3046. Implements: D7. After: 2. Issue: #3044

### Milestone: Instance identity (after Log identity)

**Done when:** DB rows, owner registries, routes, the CLI and the client all key on the instance name, and `instance_index` is display order only, so reordering config entries never moves an instance's history.

6. **DB rows keyed by instance name**: the listener and scheduled-job tables gain an `instance_name` column that replaces `instance_index` in their natural keys (executions reach their instance through their listener or job). Existing listener and job rows have no name, so the migration retires them and the next startup registers name-keyed rows (no backfill, per Posture). The log and blocking-event tables, which already store `instance_name` beside `app_key`, drop their `instance_index` column. The telemetry queries and the per-instance log filter move to the name in the same PR; until issue 8, instance routes resolve their index to a name through the app registry. Migration with no backfill, chained after issue 3's log-table migration. Updates the app-configuration docs: renaming an instance now starts a new history, and the old rows age out with retention. The retire-and-re-register migration was settled after the sketch's challenges, so challenge it against the schema and reconciliation before building. Implements: D11. After: 1, 3. Issue: #3098
7. **Registry and lifecycle keyed by instance name**: the app registry, owner registries and selective restart key on the name, and the name-overlap detection in `app_lifecycle_changes` is deleted. Keeps an index-to-name lookup for instance routes until issue 8. Implements: D11. After: 1. Issue: #3099
8. **Instances addressed by name**: instance routes, wire models, `hassette-client`, CLI `--instance` and frontend URLs use the name; `instance_index` is display order only. Ships `client_compat` ignore entries for the changed routes. Implements: D11. After: 6, 7. Issue: #3100

Applies to all: D6 (logger names stay readable labels derived from the instance name).

Close as won't-do: #740 (D6) and #739 (D8). Cross-link only: #2938. Follow-up outside both milestones: #345 (the per-app level toggle, on D4's model).

## Addendum

### 2026-10-20: auto-loaded apps no longer exist (spec 135)
Spec 135 (#3145) removes app autodetection, so there are no auto-loaded apps and D5's snake_case default for
them is moot: every instance comes from a configured section. Issue 1 (#3095, PR #3146) rebases onto spec 135
and drops that branch of the naming function. The test harness's default manifest stays `ClassName.0` until
issue 1 moves it to a user-chosen name.

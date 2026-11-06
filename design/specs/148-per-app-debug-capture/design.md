# Design: Per-app debug capture

**Date:** 2026-11-06
**Status:** built
**Mode:** sketch
**Issues:** #3679
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

Capturing one app's DEBUG lines today takes a restart. `PUT /api/logs/level` (`src/hassette/web/routes/logs.py`) changes one logger by name and has no CLI command. A reload rebuilds the app's loggers from config and drops the change. `logging.log_persistence_level` is read once in `LoggingService.on_initialize` (`src/hassette/core/logging_service.py`), so DEBUG lines don't reach the database unless that setting was DEBUG at startup. This change implements the parent's D10, simplified by D2: `logging.log_persistence_level` is removed, so the database stores whatever the loggers emit, and the switch only has to change levels. `hassette app debug <app> on|off [--instance]` and a matching API route set the app's own logger and every framework logger it owns to DEBUG. The state lives in memory, so it ends when turned off or when Hassette restarts.

Where each new piece lives:

- **Capture state:** a set of `(app_key, instance_name)` pairs on `AppRegistry` (`src/hassette/core/app_registry.py`). It sits beside the registry's other per-instance runtime state, the needs-restart records, and like them it isn't tied to an `InstanceEntry`, so it survives the unregister and re-register a reload does. Stale pairs are pruned by a new registry step called beside `prune_stale_failed` in `_start_app_unlocked` (`src/hassette/core/app_lifecycle_start_stop.py`), and an app's pairs are dropped in the `changes.orphans` loop of `apply_changes` (`src/hassette/core/app_lifecycle_changes.py`) when its config removes the app (D8). This is the parent's "held by the app lifecycle" (parent D10, Summary).
- **Level application:** `App` holds its own `debug_capture` flag, passed in by `AppFactory.create_single_instance` from the registry (D7). `App.config_log_level` and `App.owner_framework_log_level` (`src/hassette/app/app.py`) return `DEBUG` while that flag is set. Every logger an app owns is built through `Resource.resolve_log_level` (`src/hassette/resources/base.py`), which reads those two methods. That covers the app's own logger, its `Lifecycle` logger, and the logger of each child resource (`Bus`, `Scheduler`, `Api`, `StateManager` and their descendants). A newly built instance therefore picks up capture with no extra wiring, and a reload is covered. Toggling a live instance sets its flag, then re-applies levels through a new `Resource` method that resolves and applies its own logger's level and recurses into its children. `App` extends it to cover the lifecycle logger.
- **Persistence:** no floor of its own (D2). `LogPersistenceHandler` (`src/hassette/logging_.py`) stores every record it receives, and `LoggingService.on_initialize` (`src/hassette/core/logging_service.py`) stops reading a persistence level. `LogCaptureHandler`'s `log_hint` floor becomes "every record" while the persistence handler exists, and stays at `_NOTIFY_DISABLED_LEVEL` when it doesn't, which keeps the invariant that hints follow what actually persists. The setting's field, its validator, its tests and its docs go (Assumed).
- **Toggle:** `AppHandler` gets one synchronous, await-free method that updates the registry, re-applies levels on running instances, and logs the change (D9), with no lifecycle lock (D6). The routes and the CLI call through it (D3).
- **Source of truth:** the registry set is authoritative. `App.debug_capture` is a mirror, set by the factory at construction (D7) and by the toggle on live instances; the status read and the factory read the registry, and level resolution reads the mirror.
- **Status read:** `debug_capture` on `AppInstanceInfo` (`src/hassette/schemas/app_snapshots.py`), filled from the registry in `AppRegistry._info_from_entry` and its failed-entry path, mapped to `AppInstance` in `wire/src/hassette_wire/apps.py` (D4). The "Debug" column goes in `APP_LIST_COLUMNS` in `src/hassette/cli/commands/app.py`, computed from the grid entry's nested `AppSummary.instances` (`AppGridEntry`, `wire/src/hassette_wire/telemetry.py`).
- **Routes and CLI:** the two `PUT` routes in `src/hassette/web/routes/apps.py` (D3), validating with `action="start"` so the admitted names match D5 (`AppAction` in `wire/src/hassette_wire/literals.py` gains no member, and `"stop"` would wrongly admit orphans), with a new response model in `wire/src/hassette_wire/apps.py`; `cmd_app_debug` in `src/hassette/cli/commands/app.py`, registered on `apps_app` in `src/hassette/cli/__init__.py` next to `reload`.
- **Docs:** `docs/pages/operating/log-levels.md` documents the switch and states what persists after D2: every record that reaches Hassette's logging pipeline (the `hassette.*` tree and loggers in `logging.extra_loggers`), at whatever level it was emitted, including an adopted third-party logger at DEBUG whose lines can carry URLs and parameters; and that turning capture off doesn't delete stored rows, which age out with `log_retention_days` or the failsafe. `docs/pages/cli/commands.md` documents `hassette app debug`. Every page that mentions `log_persistence_level` is updated (`operating/log-identity.md`, `operating/snippets/see_framework_debug_lines.toml`, `cli/commands.md`, `core-concepts/database-telemetry.md`), with tests touching it in `tests/unit/` (`grep -rl log_persistence_level`). `hassette.schema.json` also carries the setting and is regenerated by `scripts/export_schemas.py`.

Out of scope: a CLI view that lists an app's instances (#3845; D4's column is per app until then), a timer (parent D10), the web UI (parent Breakdown), `hassette log --level` (shipped in #3703 / #3776), and raising shared-service levels, including throttle and debounce lines (parent D10). User modules' own `getLogger(__name__)` loggers aren't app-owned, so the switch doesn't change their level; after D2 their lines persist only if the logger is listed in `logging.extra_loggers`, since the persistence handler is attached only to the `hassette` tree and those loggers (`_get_loggers` in `src/hassette/core/logging_service.py`).

## Posture

- **Failure handling:** bad input fails loudly: an unknown app or instance answers 404, and a bad body answers 422. Capture itself stays best-effort, as in the parent's posture.
- **Compatibility:** clean break for config (pre-V1): `logging.log_persistence_level` is removed, with a `feat!:`-style PR title, a `BREAKING CHANGE:` footer in the PR body, and a migration section in `docs/pages/operating/upgrading.md`, and a config that still sets it fails at startup with the unknown-key `ConfigError` (Assumed). The wire field is additive and goes through the released-client compatibility check.
- **Scope:** the parent's D10, plus removing the persistence floor that would otherwise force a per-app persistence exception (D2). No timer and no web UI.
- **Rollout:** ships outright, with no flag.
- **Hardening:** project defaults. Database growth from a forgotten capture is bounded by the DEBUG failsafe tier (#3675; spec 146 D3).
- **Altitude:** `build`.

## Decisions

### D1: How is capture scoped across an app's instances?

**Situation:** an app can run several instances, and the existing actions already address either all of them (`/apps/{key}/reload`) or one of them (`/apps/{key}/instances/{name}/reload`, `--instance` on the CLI). Parent D10 says capture "covers all of the app's instances unless `--instance` narrows it." It doesn't say what happens to an instance that joins the app after an app-wide `on`, for example when a config change adds a third instance.

**Deciding factor:** one model of what "captured" means, so the status read, the app factory and the level re-apply all ask the same question.

| | A: per-instance pairs; app-wide `on` adds every configured instance | B: app-level flag plus per-instance pairs |
|---|---|---|
| State shape | One set of `(app_key, instance_name)` pairs | A set of app keys plus a set of pairs; the check ORs them |
| Instance added after an app-wide `on` | Not captured until `on` runs again | Captured |
| App-wide `on`, then `off --instance x` | Removes x; the others stay captured | Needs an exclusion set or a rule that narrows the app flag, which is a third piece of state |
| App-wide `off` | Removes every pair for the app key, whatever the name, including a stale one D8 hasn't pruned | Clears the app flag and every pair |
| What the status read reports | Each instance's own state | Each instance's state, computed from two sources |
| What peers do | Spring and Envoy toggle named loggers, which is closest to per-instance | AppDaemon's per-app `log_level` applies on every reload, which is closest to an app flag |

**Recommendation:** A. It is one set and one lookup, and every reader asks the same question. The case it misses, an instance added while capture is on, requires a config change during a debugging session, and running `on` again fixes it.
**Pick B instead if** you expect to change an app's instance list often while capturing.
**Reversibility:** easy (in-memory state only)
**Ratified:** Chose per-instance `(app_key, instance_name)` pairs, with an app-wide `on` adding every configured instance, over an app-level flag plus per-instance pairs, so every reader asks one set the same question, with an app-wide `off` removing every pair for the app key whatever the name, accepting that an instance added while capture is on isn't captured until `on` runs again. The app-wide `off` rule was added after the sketch comb and confirmed by the user.

### D2: Does the database keep its own level floor? (supersedes parent D10's "lets that app's lines past the persistence level")

**Situation:** `logging.log_persistence_level` (`src/hassette/config/models.py`) is a second floor between "emitted" and "stored". It defaults to `log_level` and a validator forbids it being stricter, so its only effect is to keep per-service and per-app DEBUG overrides out of the database: an app at `log_level: DEBUG` shows those lines on the console, but they don't persist unless this setting is lowered too, and the web UI and CLI read logs only from the database. That floor is the reason a runtime switch would need a per-app persistence exception, which the sketch-time challenge found needs its own filter, a shared predicate, a mirrored set and an owner decision. No peer has a storage floor separate from the logger level: Spring, Envoy, HA and AppDaemon change the level, and whatever is emitted goes where logs go. The floor existed to keep DEBUG volume out of the database, which #3675 now bounds by deleting DEBUG lines first.

**Deciding factor:** the least machinery that meets the Done-when, matching how peers do runtime debug.

| | A: remove the setting; the database stores what loggers emit | B: keep the setting, add a per-app persistence exception | C: keep the setting; the switch only raises levels |
|---|---|---|---|
| Captured lines reach the database and UI | Yes | Yes | No: console and `docker logs` only, which misses the Done-when |
| Machinery for capture | Level changes only | A producer-side capture filter, a shared persistence predicate, a mirrored capture set and its owner | Level changes only |
| An app at `log_level: DEBUG` in config | Persisted, same as the runtime switch | Not persisted unless the floor is lowered | Not persisted |
| Long-running service overrides at DEBUG | Persisted, and deleted first by the failsafe (#3675) | Not persisted | Not persisted |
| Config compatibility | Breaking: the setting is removed | None | None |
| What peers do | Spring, Envoy, HA, AppDaemon: one level, output follows it | No peer found | Same as A for levels, but their output is a file the user can read |

**Recommendation:** A. It deletes the cause instead of building around it, makes the runtime switch and the config path behave the same, and the cost the floor guarded against is now bounded by the failsafe.
**Pick B instead if** DEBUG overrides set in config must stay out of the database by default. **Pick C instead if** a console-only capture is acceptable.
**Reversibility:** easy (a config field can be re-added pre-V1)
**Ratified:** Chose removing `logging.log_persistence_level` so the database stores whatever loggers emit, over a per-app persistence exception or a console-only switch, so capture needs only level changes and matches how peers do runtime debug, accepting a breaking config change and that every DEBUG override, runtime or configured, now persists until the failsafe or `log_retention_days` deletes it, and that a heavy DEBUG burst can crowd other records out of the bounded log queue (`log_queue_max`) and the database write queue, visible only through the health drop counters. Raised by the sketch-time challenge's convergence finding and chosen by the user.

### D3: What shape do the API route and the CLI command take?

**Situation:** the per-app actions are `POST /apps/{key}/{start|stop|reload}` and `POST /apps/{key}/instances/{name}/{action}`, built with `action_route`. They return `ActionResponse` with an outcome for each instance (succeeded, failed, refused), and the CLI reaches them through `post_with_instance_routing`. The existing runtime level change is `PUT /logs/level`, which takes the target state in its body. Turning capture on or off sets a state and can't fail for one instance while succeeding for another.

**Deciding factor:** an idempotent state change whose response reports the resulting state.

| | A: `PUT /apps/{key}/debug` and `PUT /apps/{key}/instances/{name}/debug`, with body `{"enabled": bool}` | B: `POST .../debug/on` and `.../debug/off` through `action_route` |
|---|---|---|
| Semantics | Sets a state; repeating it is a no-op | Reads as an action; repeating it is still a no-op |
| Response | The app key and each targeted instance's capture state | `ActionResponse` with outcomes that are always `succeeded` |
| Reuses existing code | `_require_addressable_instance` for validation; a small new response model | `action_route`, `ActionResponse`, `post_with_instance_routing` |
| Precedent | `PUT /logs/level` | start, stop, reload |
| CLI | `hassette app debug <key> on\|off [--instance]` | Same |

**Recommendation:** A. Capture is a state, not an action. Under B every outcome would always be `succeeded`, which is noise a client has to handle, and a client meeting an unknown outcome has to assume failure (per `InstanceOutcome`'s docstring). The new response model is small. The CLI command doesn't ask for confirmation, like `start`.
**Pick B instead if** you'd rather every per-app mutation share one route builder and response shape, even with outcomes that carry no information.
**Reversibility:** easy pre-V1 (a wire and CLI surface)
**Ratified:** Chose `PUT /apps/{key}/debug` and `PUT /apps/{key}/instances/{name}/debug` with an `{"enabled": bool}` body, returning each targeted instance's capture state, over POST on/off actions through `action_route`, so the route reads as the idempotent state change it is, accepting a small new response model next to `ActionResponse`.

### D4: How does the status read show that capture is on?

**Situation:** parent D10 requires the app status read to show capture is on, so a forgotten capture is visible. Capture is per-instance (D1). `AppInstanceInfo` (`src/hassette/schemas/app_snapshots.py`) maps to the wire `AppInstance`, which is nested in `AppSummary.instances` and served by `GET /apps` and `GET /apps/{key}`. The CLI's `hassette app` lists the app grid (`AppGridEntry`, which nests `AppSummary`). It shows a table of apps, not instances.

**Deciding factor:** someone who forgot a capture sees it from the commands they already run.

| | A: `debug_capture: bool` on `AppInstance`, plus a "Debug" column in `hassette app` that is set when any instance is captured | B: A's field, with the CLI showing it only in `hassette app debug <key>` (no on/off argument) | C: A's field plus an app-level `debug_capture_count` on `AppSummary` |
|---|---|---|---|
| Visible without asking | Yes, in the default app listing | No: you have to think to check | Yes, through the count |
| Wire additions | One field | One field | Two fields, one derived from the other |
| CLI work | One column, computed from the instances | A read mode on the new command | One column, read straight from the count |
| Matches existing patterns | `needs_restart` sits on the instance | Same | `needs_restart_count` sits on `AppSummary` |

**Recommendation:** A. The listing is where a forgotten capture gets noticed, and the column comes from data the grid response already carries. A count would follow the `needs_restart_count` pattern, but it's derived data a client can compute itself.
**Pick B instead if** you want the `hassette app` table to stay as it is. **Pick C instead if** you'd rather match `needs_restart_count` exactly, so the UI can show a badge without iterating instances.
**Reversibility:** easy pre-V1
**Ratified:** Chose a per-instance `debug_capture: bool` on `AppInstance` plus a "Debug" column in `hassette app` (set when any instance is captured) over showing it only on demand or adding an app-level count, so a forgotten capture shows in the default listing, accepting that the CLI table says which app is captured but not which instance, since no CLI command lists instances in human output yet.

### D5: What does `on` do for an instance that isn't running?

**Situation:** an instance can be stopped, failed, or never started. The registry tracks configured instances whether or not they're running. With capture held in the registry rather than on the live `App`, setting the pair for a stopped instance is meaningful: the levels apply when it next starts, because a new `App` resolves them at construction.

**Deciding factor:** the switch works the same whatever state the instance is in.

**Recommendation:** accept `on` and `off` for any configured instance name, the set `_require_addressable_instance` admits for `start`. A non-running instance gets the pair, and its levels apply when it starts. The response reports the capture state, not the run state. `off` for an instance that isn't captured is a no-op that still answers 200.
**Pick rejecting non-running instances instead if** you want "I turned it on but nothing's being captured" to fail loudly rather than wait for a start. That case is visible anyway: the status read shows capture on and the instance stopped.
**Reversibility:** easy
**Ratified:** Chose accepting `on`/`off` for any instance `start` can address, with a non-running instance's levels applied when it starts and `off` on an uncaptured instance answering 200 as a no-op, over rejecting non-running instances, so the switch behaves the same in every instance state, accepting that `on` for a stopped instance captures nothing until it starts.

### D6: Does the toggle take the app's lifecycle lock?

**Situation:** start, stop and reload hold the app's `AppKeyLock` (`src/hassette/core/app_key_lock.py`) for the whole action, including the `startup_timeout` wait on `on_initialize` (`src/hassette/core/app_lifecycle_instances.py`). `_require_addressable_instance` in `src/hassette/web/routes/apps.py` first runs `_require_no_action_in_progress`, which answers 409 while that lock is held or queued for. A toggle behind the lock is unavailable during a slow or hung startup, which is when DEBUG is wanted most. The lock would only stop a concurrently built instance from missing the change, but app construction and registration (`AppFactory.create_single_instance`, `src/hassette/core/app_factory.py`) and `Resource.add_child` (`src/hassette/resources/base.py`) are synchronous, so an await-free toggle body can't interleave with a build.

**Deciding factor:** the switch works while an app is stuck.

| | A: no lock; validate without the 409 pre-check | B: keep the lock and the 409 | C: keep the lock, wait for it |
|---|---|---|---|
| Works during a hung startup | Yes | No, 409 for up to the startup timeout | Request blocks until the action ends |
| Effect on a concurrent reload | None | A reload can 409 briefly | Same as B |
| Atomicity against a concurrent build | The await-free toggle body | The lock | The lock |
| New code | A validation variant that skips `_require_no_action_in_progress` | None | A wait path and an HTTP timeout story |
| What peers do | Spring actuator, Envoy `/logging`, HA `logger.set_level`: standalone level calls | unknown | unknown |

**Recommendation:** A. It's the only option that works during a hung startup, and the event loop already gives the atomicity the lock was for.
**Pick B instead if** every per-app mutation must be serialized behind one lock. **Pick C instead if** you want serialization and can tolerate a request parked for the startup timeout.
**Reversibility:** easy
**Ratified:** Chose no lock, with the toggle body kept free of awaits and validated without the in-progress 409 (the instance route by a variant of `_require_addressable_instance`, the app-wide route by `_require_known_app` with no `_require_no_action_in_progress` before it), over keeping the lock with a 409 or a wait, so capture can be turned on during a hung startup or reload, accepting that the await-free body is the only thing guaranteeing a concurrent build sees the change. Raised by the sketch-time challenge and chosen by the user.

### D7: Where does a new App get its captured flag from?

**Situation:** level resolution runs inside the App's constructor (`Resource.__init__` → `_setup_logger`). Reading the registry from there goes through `hassette.app_handler`, which raises when unwired (`src/hassette/core/hassette_accessors.py`), and the user-facing `AppTestHarness` (`src/hassette/testing/app_harness.py`) never wires one before constructing the app. `App.__init__` already takes framework-supplied keyword-only arguments with defaults (`api_factory`, `cache`, `parent`), and no app in the known user corpus overrides it.

**Deciding factor:** construction can't fail or guess in any environment, including user tests.

| | A: the factory passes the flag in (keyword-only, default False) | B: tolerant registry lookup (no AppHandler means not captured) | C: the factory sets a flag after building and re-applies |
|---|---|---|---|
| Can construction fail | No | No | No |
| Guesses another component's state | No | Yes | No |
| Public surface | One keyword-only `App.__init__` argument, documented as framework-supplied | None | None, but an attribute that must be set before levels are right |
| Harness behavior | Default uncaptured; a test can pass True | Uncaptured unless the harness wires an AppHandler | Uncaptured unless the test sets the flag |
| Reload picks up capture | Yes: the factory reads the registry | Yes | Yes |
| What peers do | AppDaemon resolves per-app `log_level` from config at (re)load | unknown | unknown |

**Recommendation:** A. No failure path and no guess, and level resolution becomes a read of the App's own state, which the toggle's re-apply also uses.
**Pick B instead if** you want no change to `App.__init__`. **Pick C instead if** you want no constructor keyword and accept briefly wrong levels after construction.
**Reversibility:** easy pre-V1
**Ratified:** Chose having `AppFactory.create_single_instance` pass a keyword-only `debug_capture` flag (default False) into the App, with the level methods reading only that flag and the toggle setting it on live instances before re-applying, over a registry lookup that tolerates an unwired AppHandler or a flag set after construction, so building an App can't fail or guess in any environment, accepting one framework-supplied keyword on `App.__init__`. Raised by the sketch-time challenge and chosen by the user.

### D8: What happens to a capture pair whose instance leaves config?

**Situation:** a pair can outlive its instance's config block, and then nobody can see it. The status read lists only configured and tracked instances, and `--instance off` answers 404 for a name outside the config (`_require_addressable_instance`, `src/hassette/web/routes/apps.py`; only `stop` gets the orphan carve-out). Only an app-wide `off` (D1) or a restart ends it, and nothing prompts anyone to run one; for an app removed from config entirely, the app-wide route 404s too. The pair sits invisible, and if the name returns the instance is built captured (announced by D9's construction WARNING, but never asked for again). `AppRegistry.prune_stale_failed` (`src/hassette/core/app_registry.py`) is the existing cleanup of stale per-instance state; it runs from `_start_app_unlocked` (`src/hassette/core/app_lifecycle_start_stop.py`) and only touches failed entries in `_instances`, so it can't be reused as-is: capture pairs for stopped or never-started instances have no entry. A running orphan (an instance left running after its block was removed) still holds DEBUG levels and can only be stopped.

**Deciding factor:** no capture pair outlives the config that named it unseen.

| | A: a new prune step beside `prune_stale_failed`, keeping pairs a live instance holds, plus dropping an app's pairs when its config removes the app | B: keep stale pairs; rely on D9's construction WARNING | C: accept and document |
|---|---|---|---|
| Invisible leftover pair | Gone after the app's next start, or at once when the app leaves config | Remains until an app-wide `off` or restart | Remains until an app-wide `off` or restart |
| Running orphan | Keeps its pair, so status matches its live levels; `stop` ends both | Same | Same |
| Name returns before a start | Built captured, announced by D9 | Same | Same |
| New code | A prune step and a drop on app removal | None | A docs sentence |
| What peers do | HA's restart-scoped debug clears at next load; pruning on removal unknown | unknown | HA, Spring, Envoy: debug lasts until reset or restart |

**Recommendation:** A. It leaves no invisible pair for someone to remember to clear, and keeps the registry agreeing with a running orphan's live levels.
**Pick B instead if** capture should survive a rename-and-revert on purpose. **Pick C instead if** no code is worth a config edit mid-capture.
**Reversibility:** easy
**Ratified:** Chose pruning capture pairs whose instance name has left the app's config and that no live instance holds, with a new step beside `prune_stale_failed` at app start, and dropping an app's pairs when its config removes the app, over keeping stale pairs or documenting the limitation, so no invisible pair is left that only an app-wide `off` or a restart would end, accepting that a rename-and-revert during a capture ends that capture, and that a pair whose name returns before the app's next start comes back captured (announced by D9). Raised by the sketch-time challenge and chosen by the user; its home was corrected by the sketch comb.

### D9: Where do the capture lines go, and is a captured start announced?

**Situation:** the instance's lifecycle logger exists only while an `App` is live, but D5 lets `on` target a stopped, failed or never-started instance, and that instance later starts already captured with no toggle running. `AppHandler`'s own logger always exists, and `LogIdentityFilter` attributes a line written under bound `app_key`/`instance_name` context to that app (Assumed).

**Deciding factor:** every capture that actually begins logs the WARNING saying how it ends, with the least new code.

| | A: toggle lines on `AppHandler`'s logger with the app's context bound, plus a WARNING on the lifecycle logger whenever an App is built captured | B: toggle lines only, on `AppHandler`'s logger with context bound |
|---|---|---|
| Stopped instance: `on`, later start | Announced at `on` and at start | Announced at `on` only |
| Reload of a captured instance | WARNING again on each reload | Silent |
| Attribution | Bound context for toggle lines; owned lifecycle logger at construction | Bound context |
| New code | One log call in the toggle, one at App construction | One log call in the toggle |
| Parent D10's "turning it on logs a WARNING" | Holds for every start of capture | Holds for the toggle only |

**Recommendation:** A. A reload or later start is when someone reading the app's logs needs to see capture is on, for one log call. The toggle's on and off lines are both WARNING, so they are emitted even when `logging.app_handler` is quieted; the on line says capture ends at `off` or restart.
**Pick B instead if** a WARNING on every reload of a captured app is noise you'd rather avoid.
**Reversibility:** easy
**Ratified:** Chose logging each toggle on `AppHandler`'s logger under the app's bound context, plus a WARNING on the lifecycle logger whenever an App is built captured, over toggle lines only, so every start of capture, including a stopped instance's later start and each reload, says capture is on and how it ends, accepting a WARNING on every reload of a captured instance and a WARNING-level off line. Raised by the sketch comb and chosen by the user.

## Assumed

- Every logger an app owns lives under `hassette.apps.<instance_name>` and is built through `Resource._setup_logger` → `resolve_log_level`. The level comes from `App.config_log_level` for the app's own logger, and from `owner_framework_log_level()` or the resource's `config_log_level` for framework loggers. `App._setup_logger` builds the `Lifecycle` logger the same way. Evidence: `src/hassette/resources/base.py` (`_setup_logger`, `resolve_log_level`, `owner_framework_log_level`) and `src/hassette/app/app.py` (`_get_logger_name`, `_setup_logger`, `APP_LOGGER_PREFIX`).
- `App` sets `_app_key` and `app_config` before `Resource.__init__` runs `_setup_logger`, so a flag set in the same place is visible to level resolution at construction. Evidence: `App.__init__` in `src/hassette/app/app.py`.
- A config key that matches no field fails startup with `ConfigError`, listing the key and a suggestion, so a config still setting `log_persistence_level` stops with a message rather than being silently ignored. Evidence: `check_unknown_keys` in `src/hassette/config/checks.py`.
- The persistence handler can be absent when its creation fails. Capture then still raises levels, so lines reach the console, but nothing persists. Evidence: the `except` branch in `LoggingService.on_initialize`.
- `LogIdentityFilter` stamps `app_key` and `instance_name` from bound structlog context for a logger with no owner identity, so a framework line written under that context is attributed to the app. Evidence: `LogIdentityFilter.filter` in `src/hassette/logging_.py`.
- `log_hint` is one WebSocket message per persisted record; the frontend coalesces bursts into one refetch (`frontend/src/components/shared/log-table/use-log-data.ts`). Under D2, a captured app's DEBUG lines each send a hint, which is accepted with D2's queue-pressure limitation. Evidence: `LogCaptureHandler.emit` in `src/hassette/logging_.py`.
- Turning capture off re-resolves levels from config, so an app configured at DEBUG stays at DEBUG, and any `PUT /logs/level` change to one of the app's loggers is overwritten by the toggle. Evidence: parent D10.
- DEBUG lines persisted under capture are the failsafe's first deletion target and age out on `log_retention_days`. Evidence: spec 146 (#3675, built).
- Wire changes regenerate schemas and frontend types (`scripts/export_schemas.py --types`), and the docs pages that cover runtime log levels and the CLI get updated: `docs/pages/operating/log-levels.md` and `docs/pages/cli/commands.md`. Evidence: parent Breakdown "Applies to all"; `grep -l logs/level docs/pages`.

## Decisions carried from the parent

- Parent D10: a per-app switch, ended by turning it off or by a restart. It covers the app's own logger and owned framework loggers, never shared services. It never touches config. It logs a WARNING when turned on, and the status read shows it. Carried, with no timer; its persistence exception is superseded by D2.
- Parent D9 as amended by spec 146 D3: DEBUG lines are the failsafe's first target, on the shared row budget.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- `LogCaptureHandler`'s level floor became a `hints_enabled` boolean: with no persistence floor, the only two states left are "every record" and "none", so the level-valued setter and the `_NOTIFY_DISABLED_LEVEL` sentinel had nothing left to express.
- The status field is set in `AppRegistry._combine_instance_info` (covering running, failed and flagged instances) and on `build_manifest_info`'s STOPPED placeholder, rather than in `_info_from_entry`: a stopped or never-started instance has no entry, and D5 lets it be captured.
- `Resource.reapply_log_levels` also re-applies the resource's own `TaskBucket` when that bucket's parent is the resource: TaskBuckets aren't in `children`, but their loggers resolve through the owning app like any child's.
- The toggle re-applies levels on every targeted running instance but logs only for instances whose registry state changed: re-applying is idempotent and repairs an App flag that drifted from the registry, while a WARNING for a repeated `on` would announce a change that didn't happen.
- API schema bumped to 6 (`API_SCHEMA_VERSION`, `MIN_API_SCHEMA_VERSION`): the client's new `set_debug_capture` depends on routes v0.63.0 lacks (`.claude/rules/client-schema-floor.md`).
- The `hassette app` column cap test rises from 9 to 10, as #3550 did for the Restart column, to fit D4's Debug column.
- The CLI command pre-checks `--instance` against the app list and warns on a server-confirmed mismatch, as `start`/`stop`/`reload` do, so a typo gets the same error in every `hassette app` subcommand.
- The debug routes validate with `_require_manifest` plus a configured-name check, not `_require_known_app`/`_require_addressable_instance` with a borrowed `"start"` action: the admitted names are the same (D5), without reading as a start.
- An app removed from config also has capture ended on any instance its stop left running, since its debug routes answer 404 and nothing else could end it.
- `App.set_debug_capture` sets the flag and re-applies levels in one call, so the toggle can't do half of it.
- `log_hint` broadcasts are coalesced in `LogCaptureHandler` (one pending hint at a time) instead of one per record as Assumed states: with no persistence floor, a captured app's DEBUG burst otherwise scheduled one main-loop task and JSON round-trip per line. A 20,000-record DEBUG burst went from 20,000 broadcasts to 1-2. The frontend only uses a hint as a refetch signal, so one hint can stand for several records.
- The public `stop_app`/`stop_instance` prune capture pairs no configured or running name holds, so D8's "`stop` ends both" holds for a running orphan; a reload's internal stop doesn't, since the start that follows prunes the same way.
- The removed-app capture clear in `apply_changes` runs in a `finally` around the orphan's stop, so a cancelled stop doesn't strand capture behind routes that answer 404.
- The capture WARNINGs no longer say every line is stored: with persistence down they would claim storage that isn't happening.

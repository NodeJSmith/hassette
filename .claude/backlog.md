## Visual QA — 2026-03-23

### 1. Handler descriptions truncate the most important information — HIGH
App detail handler rows show full dotted-path strings that bury entity IDs mid-string. Ellipsis cuts off the most critical info. Extract entity ID as a separate visible field.

### 2. No way to enable a disabled app from the UI — HIGH
Disabled apps have no Enable button on detail page or apps list. Users must edit config files. Add Enable/Start button for disabled apps.

### 3. App detail sections lack visual rhythm — same spacing inside and between — HIGH
Inter-section gap (~16px) matches intra-section padding. Section boundaries are ambiguous. Double inter-section spacing to ~32px.

### 4. Action buttons dominate the apps list table — MEDIUM
Stop/Reload stacked vertically make rows ~80-90px. 12+ outlined colored buttons compete for attention. Side-by-side, ghost style, or overflow menu.

### 5. "Connected" bar wastes prime vertical real estate — MEDIUM
40px full-width bar communicates one bit (connected/not) that's true 99.9% of the time. Collapse to status dot in sidebar; reserve full bar for disconnected.

### 6. Empty sections waste space on app detail — MEDIUM
"Event Handlers (0 registered)" and "Scheduled Jobs (0 active)" take ~80px each for zero content. Collapse or make compact single line.

### 7. Stop button lacks visible hover feedback — MEDIUM
Destructive action shows no visible change on hover. No confirmation dialog either. Add hover state.

### 8. Status badge uses three different treatments for "running" — LOW
Dashboard cards: green text + dot. Apps list: green pill badge. App detail KPI: large green text. Unify to one treatment.

## Web Stack Audit — 2026-03-24

### 1. Hardcoded zero in dashboard KPI: avg_job_duration_ms always shows 0 — CRITICAL
`src/hassette/web/routes/telemetry.py:185` — Job duration KPI hardcoded to `0.0` instead of computed from job executions. Misleading metric on dashboard.

### 2. API contract drift: frontend ListenerData missing ~16 backend fields — CRITICAL
`frontend/src/api/endpoints.ts:60-72` vs `src/hassette/web/models.py:301-327` — Backend returns 27 fields, frontend declares 11. Advanced handler metrics silently discarded.

### 3. ConnectedWsMessage missing timestamp field — CRITICAL
`src/hassette/web/models.py:221-224`, `frontend/ws-schema.json:152-169` — Only WS message type without `timestamp`. Frontend code assuming `msg.timestamp` gets `undefined` on reconnect.

### 4. Dead code: compute_app_grid_health() never called + duplicate logic — HIGH
`src/hassette/web/telemetry_helpers.py:153-181` — Duplicates logic inlined in `routes/telemetry.py:192-237`. Never imported. Maintenance hazard.

### 5. Stub endpoint /scheduler/history returns empty array — HIGH
`src/hassette/web/routes/scheduler.py:52-59` — Exposed in OpenAPI, accepts params, always returns `[]`.

### 6. Frontend error responses never parsed — HIGH
`frontend/src/api/client.ts:16-30` — Backend `HTTPException(detail=...)` wraps as `{"detail": "..."}` but frontend only captures HTTP status text, not the detail field.

### 7. No schema validation tests in CI — HIGH
`frontend/openapi.json` and `frontend/ws-schema.json` have no CI test validating they match backend models. Schema drift happens silently.

### 8. Broad except Exception in telemetry: silent dashboard failures — HIGH
`src/hassette/web/routes/telemetry.py:202` — Database errors, timeouts, coding mistakes all silently return empty summaries. No user-visible error.

### 9. Component test coverage: 0/25 frontend components tested — HIGH
Hooks/utils at 100% but no component tests for LogTable, ManifestList, ActionButtons, or any page.

### 10. Silent WebSocket message drops for slow clients — HIGH
`src/hassette/core/runtime_query_service.py:318-328` — Queue saturation logged at DEBUG only, no metrics, no backpressure.

### 11. Naming drift: "listeners" (backend) vs "handlers" (frontend) — LOW
Same concept, different names across the stack. Creates confusion during cross-stack debugging.

### 12. Type mismatch in bus.py: response_model vs return type — LOW
`src/hassette/web/routes/bus.py:15-24` — `response_model=list[ListenerMetricsResponse]` but return type is `list[ListenerSummary]`.

### 13. Missing response_model on mutation endpoints — LOW
`routes/apps.py`, `routes/services.py`, `routes/config.py` return bare dicts. OpenAPI shows `object` instead of specific fields.

### 14. WebSocket nesting depth 4 — LOW
`src/hassette/web/routes/ws.py:42-60` — Message handling could be extracted for readability.

## Docs Challenge — 2026-04-03

### 1. `run_hourly(minute=15)` raises TypeError at runtime — CRITICAL
`docs/pages/core-concepts/apps/index.md:53` — First recurring-task example uses nonexistent `minute` param. Also `api_port` in AppDaemon comparison is invalid.

### 2. Config file-discovery table duplicated across 4 pages with drift — CRITICAL
Same search path list in `getting-started/index.md`, `getting-started/configuration.md`, `configuration/index.md`, `configuration/auth.md`. Already diverging.

### 3. `run_daily` described as "once a day at a specific time" — actually an interval — HIGH
`scheduler/methods.md:47` — Misleading description; `start=` is first-run only, not a recurring anchor.

### 4. Web API unauthenticated, binds 0.0.0.0 — no warning in docs — HIGH
No auth middleware on control endpoints (start/stop/reload). Docs never mention the exposure.

### 5. `getting-started/configuration.md` is a ghost page — HIGH
No unique content. Creates 3 competing "configuration" nav entries. Delete and migrate screenshot.

### 6. Scheduler methods page has no parameter documentation — HIGH
No parameter tables, types, defaults, or `if_exists`/`TimeDelta | float` docs. Prose + snippets only.

### 7. First-app snippet uses `D.StateNew[states.SunState]` with no introduction — HIGH
Tutorial's first code example depends on DI concepts not explained until 3 sections later.

### 8. `data_dir` default documented as `~/.hassette` — actual is `platformdirs` path — HIGH
Linux: `~/.local/share/hassette/v1/`. Major version upgrades silently rotate path.

### 9. DI content duplicated in `handlers.md` and `dependency-injection.md` — HIGH
Same 3 patterns + annotation tables in both, already diverging. Trim handlers.md to a gateway.

### 10. No troubleshooting index — HIGH
Content scattered across 4+ pages (docker, scheduler, storage, custom-states). No top-level entry point.

### 11. `basic_config.toml` uses `name =` instead of `instance_name =` — HIGH
Silently ignored at runtime due to `extra="allow"`. User's instance name never appears.

### 12. Docker `docker-compose.yml` snippet missing `ports:` — Web UI unreachable — HIGH
Guide says UI is at `:8126` but snippet has no port mapping.

### 13. Getting-started TOML defines `greeting` but first app never uses it — HIGH
Screenshot shows output the tutorial app literally cannot produce.

### 14. `whenever`/`ZonedDateTime` used throughout with no introduction — HIGH
`self.now()` returns `ZonedDateTime` from `whenever` library. Never introduced. Readers using stdlib `datetime` get runtime errors.

### 15. 20+ global config fields undocumented — MEDIUM
Includes `extend_autodetect_exclude_dirs` (trap: the override field silently wipes defaults), all `service_restart_*` backoff fields.

### 16. Architecture diagram omits 6 real services — MEDIUM
EventStreamService, SessionManager, CommandExecutor, ServiceWatcher, FileWatcherService, WebUiWatcherService.

### 17. Persistent storage shared-cache warning buried after examples that don't use safe pattern — MEDIUM
None of the examples use `instance_name` key prefixing despite the shared-cache collision risk.

### 18. `App[AppConfig]` generic used inconsistently — MEDIUM
Tutorial uses `App[AppConfig]`, core-concepts uses `App` without generic. Reader can't tell which is correct.

### 19. `on_ready` lifecycle hook used in example but not documented on lifecycle page — MEDIUM
`persistent-storage.md:352` uses it. Lifecycle page documents only `on_initialize`/`on_shutdown`.

### 20. `appdaemon-comparison.md` uses nonexistent `api_port` field — MEDIUM
`api_port = 8123` not in config schema. Silently ignored or validation error.

### 21. Nav places "Hassette vs. YAML" before "Local Setup" — MEDIUM
Decision content blocks the install path for committed users.

### 22. `advanced/index.md` duplicates conceptual content from child pages — MEDIUM
Other index pages use short intro + links. This one re-explains each topic in paragraphs.

### 23. AppDaemon comparison is a nav dead-end — MEDIUM
No "Next Steps" section or links back into main docs tree.

### 24. `P` predicate alias import path inconsistent/missing — MEDIUM
Filtering page never shows import for `P`. Different pages use different import paths.

### 25. Database degraded-mode recovery guidance too vague for Docker — MEDIUM
No Docker volume paths, no commands, no confirmation that deleting DB is safe.

### 26. `core-concepts/index.md` service list mostly unlinked — MEDIUM
10 services listed, only 1 linked. No navigation path for 6+ services.

### 27. Log level table duplicated between `global.md` and `log-level-tuning.md` — MEDIUM
13-field table maintained in two places.

### 28. `auth.md` is mostly file-discovery content, not authentication — MEDIUM
Lines 22-43 re-state file paths. Will partially resolve with Finding 2.

### 29. "Hassette vs. YAML" lacks setup-cost and coexistence info — MEDIUM
Decision page never says whether Hassette runs alongside HA automations.

### 30. CHANGELOG.md not in mkdocs nav — MEDIUM
59KB file exists at repo root but unreachable from docs site.

### 31. Custom state usage snippets diverge between `custom-states.md` and `state-registry.md` — MEDIUM
Different base classes in "basic custom state" examples create inconsistent mental models.

### 32. Lifecycle warns against overriding `cleanup` without explaining what it is — MEDIUM
`cleanup` mentioned nowhere else on the page. No explanation of why methods are final.

### 33. Local setup has no success criteria — MEDIUM
Says "run `hassette`" with no expected output. Docker guide correctly shows what to look for.

### 34. Getting-started step ordering — TOML references app file before it exists — MEDIUM
`hassette.toml` (step 5) references `main.py` created in step 6.

### 35. `AppConfig`/`BaseSettings` used without explaining `pydantic-settings` — MEDIUM
Separate package from Pydantic core. No import shown for `SettingsConfigDict`.

### 36. Pattern 3 labeled "recommended" before reader has context — MEDIUM
Directs new users to the most complex DI pattern before they understand DI.

### 37. `run_cron` docs don't show string expression support — LOW
Only integer values in table. `*/5`, `1,3,5` syntax undocumented.

### 38. Local users never told about web UI — LOW
Local setup guide doesn't mention the web UI or `http://localhost:8126/ui/`.

### 39. CHANGELOG not linked from landing page — LOW
Subsumed by Finding 30.

### 40. Prose snippets not single-sourced — ".env" warning in 3+ places — LOW
`pymdownx.snippets` used for code but not for repeated prose fragments.

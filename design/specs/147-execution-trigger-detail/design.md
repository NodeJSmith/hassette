# Design: Execution Trigger Detail

**Date:** 2026-11-05
**Status:** ratified
**Mode:** sketch
**Issues:** #3676
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

A handler execution stores `trigger_context_id` and `trigger_origin`, but not which event, entity or value change fired it, so a wildcard or multi-entity listener's run can't say what triggered it. This change records an event summary on every handler execution and shows it through the API, the wire model, the client and `hassette execution <id>`. It implements the parent's D6 as refined by D1 and D3 below, except `caused_by`, which ships with #3677.

Where each new piece lives:

- **Columns:** migration `src/hassette/migrations_sql/023.sql` adds nullable `executions` columns `trigger_topic`, `trigger_entity_id`, `trigger_old_value`, `trigger_new_value` and `trigger_parent_id`, next to the existing `trigger_context_id` and `trigger_origin`. Job rows leave all seven NULL.
- **Record fields:** matching optional fields on `ExecutionRecord` (`src/hassette/core/execution_record.py`), flowing through `execution_insert_params` (`src/hassette/core/telemetry/insert_params.py`, which derives the INSERT column list) and `_EXECUTION_SELECT_COLUMNS` (`src/hassette/core/telemetry/execution_queries.py`).
- **Extraction:** one module-level function in `src/hassette/core/execution_record_builder.py` that turns `(event, listener)` into the summary fields. `build_execution_record` calls it for `InvokeHandler`, and `BusService._record_predicate_failure` (`src/hassette/core/bus_service.py`) calls it for predicate-error rows (D5). It never raises: any failure leaves the fields NULL and logs per Posture.
- **Synthetic events:** `make_synthetic_state_event` in `src/hassette/core/bus_service.py` builds its context from the cached state and uses the base topic (D7).
- **Tracked attribute name:** `EntityWatch.attribute` in `src/hassette/bus/listeners.py`, set by `on_attribute_change` in `src/hassette/bus/bus.py` (D4).
- **Wire:** a new `ExecutionTrigger` model in `wire/src/hassette_wire/telemetry.py` with fields `topic`, `entity_id`, `old_value`, `new_value`, `context_id`, `parent_id` and `origin` (each `str | None`, mapping one-to-one onto the seven columns), carried as `Execution.trigger: ExecutionTrigger | None` (D1). The row-to-wire mapping in `execution_queries.py` sets `trigger` to `None` exactly when `kind == "job"`; every handler row gets an object, with unset fields `None`, so a pre-023 row keeps its context and origin and a row whose extraction failed still shows them.
- **CLI:** `cmd_execution` in `src/hassette/cli/commands/log.py` also calls `GET /api/telemetry/execution/{id}` (it already exists, and so does the client's `get_execution`) and shows the trigger above the log table (D6).
- **Frontend:** `execution-detail.tsx`, `execution-table.tsx`, `test/factories.ts` and `execution-detail.test.tsx` move to the new shape. There's no new UI: the existing trigger block keeps showing context and origin. Generated types and schemas come from `scripts/export_schemas.py --types`. UI display is out of scope per the parent's "Applies to all" line.
- **Docs:** `docs/pages/cli/commands.md` and `docs/pages/cli/workflows.md` cover the new `hassette execution` output. `docs/pages/core-concepts/database-telemetry.md` covers the new execution fields. `docs/pages/core-concepts/internals/service-details.md` follows D4's rename (its `DurationConfig` autoref and description). `database-telemetry.md` also carries D8's and D2's sentences. Field and method docstrings change with the code.

Out of scope: `caused_by` (#3677), near-miss rows (#1817, which reuses this summary shape later), new UI, and backfilling existing rows.

## Posture

- **Failure handling:** best-effort, carried from the parent. Building the summary never raises into dispatch or a handler; a failure leaves the fields NULL and logs through `logger.exception` with no values, once per failing event, which is loud on purpose if a payload change breaks every row.
- **Compatibility:** clean breaks (pre-V1). Wire changes go through `client_compat` and `check_wire_compat`; an accepted break gets an ignore-file entry with a reason.
- **Scope:** the issue's acceptance criteria only. The frontend changes only to keep its existing readers working.
- **Rollout:** ships outright. Migration `023` adds nullable columns, with no backfill.
- **Hardening:** project defaults. Row growth is bounded by D2's limit. Values are stored as Home Assistant reports them, with no redaction (D2); `docs/pages/core-concepts/database-telemetry.md` says so.
- **Altitude:** `build`.

## Decisions

### D1: How does the wire model carry the trigger?

**Situation:** `Execution` (`wire/src/hassette_wire/telemetry.py`) has flat `trigger_context_id` and `trigger_origin` fields that are `None` on jobs. The parent's D6 asks for "one nested `trigger` object, absent on jobs", but its posture says wire changes are "additive". This pickup's posture allows clean breaks. The released client parses `Execution` with Pydantic's default `extra="ignore"` and gives the flat fields `None` defaults, so it parses every option below. It would show `None` for context and origin if the flat fields went away. Four frontend files read the flat fields. `trigger_mode` ("manual") applies to jobs too, so it stays flat in every option.

**Deciding factor:** one place to read every trigger fact, as D6 asks, without two copies of the same field.

| | A: nested `trigger`, flat pair removed | B: nested `trigger`, flat pair kept | C: flat fields only (five more `trigger_*` fields) |
|---|---|---|---|
| Matches parent D6 | Yes | Yes | No (supersedes D6's nested object) |
| Matches parent's "additive" | No | Yes | Yes |
| Same fact in two places | No | Yes, context id and origin | No |
| Released client | Parses; context and origin read `None` | Unchanged | Unchanged, new fields ignored |
| Compat ignore entries | Likely, for removed fields | None | None |
| Jobs | `trigger: None` | `trigger: None`, flat `None` | Five more `None` fields |
| Frontend work | Update 4 files | None required | None required |
| #1817 near-miss reuse | Reuses `ExecutionTrigger` | Reuses `ExecutionTrigger` | Copies the five fields |

**Recommendation:** A, because it gives one home for trigger facts and a model #1817 can reuse. Pre-V1 allows the break, and the released client still parses. This supersedes the parent's "additive" posture for this one model.
**Pick B instead if** a deployed client or script reads `trigger_context_id` and you want it to keep working until V1. **Pick C instead if** you'd rather not introduce a nested wire model before #1817 confirms the shape.
**Reversibility:** easy until V1 (wire shape)
**Ratified:** Chose a nested `trigger` object with the flat `trigger_context_id`/`trigger_origin` removed, over keeping the flat pair or going flat-only, to give trigger facts one home that #1817 can reuse, accepting a clean wire break (released clients read `None` for context and origin) and four frontend files to update.

### D2: How are old and new values stored, and where are they truncated?

**Situation:** state values are strings, which Home Assistant caps at 255 characters. Tracked attributes can be any JSON value, such as a number, a list or a dict, and some are large (`entity_picture` URLs, `source_list`). The parent estimated about 100 bytes per handler row. Nothing in hassette truncates a stored value yet, so there's no convention to follow.

**Deciding factor:** a readable value in the CLI and API with a hard bound per row.

| | A: display string, 255-char cap | B: display string, 1024-char cap | C: JSON value, dropped over the cap |
|---|---|---|---|
| Storage | TEXT: strings as-is, other values `json.dumps` (compact) | Same | TEXT holding JSON; the wire type is `Any` |
| Over the limit | Cut to 255 with a trailing `…` | Cut to 1024 with `…` | NULL, plus a `truncated` flag |
| Worst case per row (two values) | About 0.5 KB for ASCII, up to about 2 KB for 4-byte code points | About 2 KB ASCII, up to about 8 KB | Same as A at a 255 cap |
| Full state values kept | Always (HA's own cap) | Always | Always |
| Typed on the wire | No: `"21.5"`, not `21.5` | No | Yes |
| A list or dict attribute | Readable until the cut | Readable to 1 KB | Shown whole or not at all |
| New fields | None | None | A flag |

**Recommendation:** A, because 255 matches Home Assistant's own state limit, so no state value is ever cut, and the bound stays close to the parent's size estimate. A trailing `…` marks a cut value without a flag. Values are for reading, not for parsing.
**Pick B instead if** you often track large attributes and want them whole. **Pick C instead if** callers should get typed values they can compare in code.
**Storage rule:** a string value is stored as-is; any other value is stored as `json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)`. A missing state or attribute stores NULL, while an explicit JSON `null` stores `"null"`. The 255 limit counts code points of the stored string, `…` included.
**Reversibility:** easy (a constant; existing rows keep their cut)
**Ratified:** Chose display strings (strings as-is, other values as compact `json.dumps` with `ensure_ascii=False` and `default=str`; NULL for a missing value, `"null"` for an explicit null) cut at 255 code points with a trailing `…`, over a 1024 cap or typed JSON values dropped over the cap, to match Home Assistant's own state limit and keep rows near the parent's size estimate, accepting untyped values on the wire, cut-off large attributes, and values stored as Home Assistant reports them with no redaction.

### D3: What does the "event type" column hold?

**Situation:** Home Assistant events carry `event_type` (`state_changed`). Hassette's own events (`HassettePayload`) don't have one; they only have a topic. `event.topic` is the concrete topic, such as `hass.event.state_changed`, while `InvokeHandler.topic` is the route the listener matched, which can be a glob.

**Deciding factor:** one field that's filled for every handler run.

| | A: `event.topic` | B: HA `event_type` |
|---|---|---|
| Hassette-internal events | Filled (`hassette.*`) | NULL |
| HA events | `hass.event.state_changed` | `state_changed` |
| One shape per event kind (with D7) | Yes | Yes |

**Recommendation:** A, stored as `trigger_topic` and shown as `trigger.topic`, superseding the parent D6's "event type" wording, because it names the event kind and is never empty. It is the event's own topic, not the route the listener matched (`hass.event.state_changed`, never `hass.event.state_changed.light.office`); the entity has its own column, and the route is joinable through `listener_id`. Synthetic events carry the same base topic (D7), so every row of one event kind has one topic shape.
**Pick B instead if** you want the field to read like Home Assistant's own event names.
**Reversibility:** easy
**Ratified:** Chose the event's own topic (`trigger_topic` / `trigger.topic`) over Home Assistant's `event_type`, to name the event kind on every handler run including Hassette's own events, accepting the longer `hass.event.` prefix on Home Assistant events and that the matched route is only available through the listener.

### D4: Where does a listener keep the attribute it tracks?

**Situation:** `on_attribute_change(entity_id, attr, ...)` (`src/hassette/bus/bus.py`) turns `attr` into predicates through `build_attr_preds`. The listener keeps only `DurationConfig.is_attribute_listener: bool` (`src/hassette/bus/listeners.py`). Every `on_state_change` and `on_attribute_change` listener gets a `DurationConfig` holding its `entity_id`, even without a duration, so it is really the listener's entity-tracking config with a duration-specific name. To store "the tracked attribute's old and new values", the extraction function needs the attribute name. This is a structural gap: there's no field for it today.

**Deciding factor:** the name sits next to the facts it belongs with, without a rename this issue doesn't need.

| | A: `DurationConfig.attribute: str \| None`, replacing the bool | B: new `Listener`/`ListenerIdentity` field | C: rename `DurationConfig` to an entity-tracking config, then A |
|---|---|---|---|
| Sits with `entity_id` and the attribute-listener flag | Yes | No | Yes |
| Fixes the misleading class name | No | No | Yes |
| Diff size | Small: the bool becomes a property, `None` means a state listener | Small | About 195 mechanical references in 19 files (66 in 5 source files, the rest tests), checked by pyright; `DurationConfig` is exported from `hassette.bus` (no uses in the hautomate corpus) |
| One source of truth for "attribute listener" | Yes (derived from `attribute`) | No: bool and name stay separate | Yes |
| Host's spread | Bus and duration-hold modules only | Wider (identity also feeds DB registration) | Same as A |

**Recommendation:** A, because the attribute belongs with the entity the config already tracks, and replacing the bool removes a fact that would otherwise need to stay in sync with it. The naming debt is pre-existing. (The user overrode this and chose C after the measured blast radius; see Ratified.)
**Pick B instead if** you'd rather keep `DurationConfig` about durations and accept the duplicated flag. **Pick C instead if** you want the rename now and accept the larger diff.
**The bool goes away:** `is_attribute_listener` is deleted, not kept as a property. Its readers (`compute_elapsed` in `src/hassette/core/bus_service.py`, `_duration_configs_match`) test `attribute is not None`, and `Bus._subscribe` takes `attribute: str | None` in place of its `is_attribute_listener` parameter.
**Equality:** `_duration_configs_match` (renamed with the class) and its docstring compare `attribute` in place of `is_attribute_listener`, so two watches differing only in tracked attribute don't match. The renamed `hassette.bus` export is announced in the PR's single `BREAKING CHANGE:` footer (see `## Build`).
**Reversibility:** easy (internal)
**Ratified:** Chose renaming `DurationConfig` to `EntityWatch` (`Listener.duration_config` to `Listener.entity_watch`) and adding `attribute: str | None` in place of the `is_attribute_listener` bool, with watch equality comparing `attribute`, over adding the field without a rename or adding a separate listener field, to fix the misleading name while the attribute joins the entity it belongs to, accepting about 195 mechanical references changed in a separate `refactor:` commit before the feature commit and the renamed `hassette.bus` export named in the PR's `BREAKING CHANGE:` footer. `DurationHoldManager` and `DurationTimer` keep their names.

### D5: Which handler rows outside a normal run get trigger detail?

**Situation:** two handler rows aren't built through `build_execution_record`'s normal path. **Synthetic immediate-fire** runs (`immediate=True`) use an event built from the cached state, with `old_state=None`. Today they null the context id and set origin to `HASSETTE_SYNTHETIC`, because the event has no Home Assistant counterpart. **Predicate-error** rows (`BusService._record_predicate_failure`) record an error execution with no trigger fields at all, though the event that broke the predicate is in hand.

**Deciding factor:** every handler row that has a real entity and value says so.

| | A: both get topic, entity and values (and, with D7, the real context) | B: only normal runs; both others leave the new fields NULL | C: predicate-error rows get everything, synthetic stays as today |
|---|---|---|---|
| "Which entity broke my `where=`" | Answered | Not answered | Answered |
| Immediate fire shows its starting value | Yes (new value; old NULL) | No | No |
| Synthetic context stays honest | Yes | Yes | Yes |
| Extra code | One more call site | None | One more call site |

**Recommendation:** A, because both rows carry a real entity and value. With D7, a synthetic event carries the real context of the change that set the cached state, so synthetic rows record that context id and parent id instead of NULL; normal immediate-fire rows keep origin `HASSETTE_SYNTHETIC` from `InvokeHandler.is_synthetic`. Predicate-error rows record the event's context id and origin too, which today's wire docstring says they lack. That docstring changes with the model.
**Pick B instead if** you want this issue limited to the normal run path. **Pick C instead if** a synthetic row's value looks too much like a real change to you.
**Reversibility:** easy
**Ratified:** Chose recording topic, entity, values and context on both immediate-fire and predicate-error rows (immediate-fire rows carrying the real context of the change that set the cached state, per D7), over normal runs only or predicate-error rows only, so every handler row with a real entity and value says so, accepting one more call site in `BusService`.

### D6: How does `hassette execution <id>` show the trigger, including in `--json`?

**Situation:** `cmd_execution` calls `GET /api/executions/{id}` and renders only log lines, as a table or as a JSON list. The execution itself, trigger included, comes from `GET /api/telemetry/execution/{id}`, which can return `null` when the row has been retained away or isn't flushed yet. #3677 later adds `caused_by` and API writes to this same view (parent D13).

**Deciding factor:** one command that shows trigger and logs, with room for #3677's additions.

| | A: trigger block above logs; `--json` becomes `{"execution": ..., "logs": [...]}` | B: trigger block in human mode only; `--json` unchanged | C: new `hassette execution show` subcommand |
|---|---|---|---|
| Trigger in one command | Yes | Yes, except in JSON | Two commands |
| Breaks `--json` scripts | Yes (pre-V1) | No | No |
| Room for #3677 | Add keys to the object | JSON can't show them | Yes |
| Execution not found | Block reads "execution record not found"; logs still shown | Same | Error |
| Calls | Two | Two (one in JSON) | One each |

**Recommendation:** A, because Claude-driven troubleshooting reads `--json`, and a single object leaves room for #3677. Jobs have no trigger block, but the execution summary (kind, status, duration) still shows.
**Pick B instead if** existing scripts parse `hassette execution --json` as a list. **Pick C instead if** you want logs and the record as separate commands.
**Missing or failed record:** when the execution call returns `null`, `--json` holds `"execution": null`, the command exits 0, and the logs are still shown; human mode says the record is "not recorded yet (rows are written in batches) or removed by retention; retry in a few seconds". A failed execution call is reported on stderr and treated as `null`. A failed logs call fails as it does today. `docs/pages/cli/commands.md` documents this.
**Reversibility:** easy until V1 (CLI output)
**Ratified:** Chose a summary and trigger block above the log table, with `--json` becoming `{"execution": ..., "logs": [...]}`, over a human-only block or a separate subcommand, to show trigger and logs in one command with room for #3677's additions, and a lenient contract when the record is missing or its call fails (`"execution": null`, exit 0, logs shown, a message naming batching and retention) over a strict non-zero exit, so logs reach the user in the seconds after a failure, accepting a pre-V1 break for scripts that parse `--json` as a list and scripts having to check for `null` rather than an exit code.

### D7: How is the synthetic immediate-fire event built?

**Situation:** for `immediate=True` and the duration fire-time recheck, `make_synthetic_state_event` (`src/hassette/core/bus_service.py`) builds a `RawStateChangeEvent` with `old_state=None`, the cached state as `new_state`, topic `hass.event.state_changed.<entity_id>` (real events carry only `hass.event.state_changed`), origin `LOCAL`, and a fresh random `uuid4()` context id. The only synthetic marker is `InvokeHandler.is_synthetic`, read once by `build_execution_record`. Code that holds only the event (the trigger extractor, `BusService._record_predicate_failure`, and #1817's near-miss rows later) can't tell, so it would record a fabricated context id as if Home Assistant issued it, and a second topic shape. The cached `HassStateDict` already carries the real `context` of the change that last set the state (`Required` in `src/hassette/events/hass/raw.py`). Raised by the sketch-time challenge's convergence finding; peers surveyed in `design/research/2026-11-05-immediate-fire-synthetic-events/prior-art.md`.

**Deciding factor:** nothing fabricated on any row, with the least new machinery.

| | A: real context + base topic; keep the command-side label | B: A, dropping `is_synthetic` entirely | C: A, plus a synthetic marker on the payload | D: keep the event; work around it per consumer |
|---|---|---|---|---|
| Fabricated context anywhere | No | No | No | Avoided only where each consumer knows to |
| Normal immediate-fire rows | Real context, origin `HASSETTE_SYNTHETIC` | Real context, origin `LOCAL`, told apart only by NULL old value | Real context, `HASSETTE_SYNTHETIC` | NULL context, `HASSETTE_SYNTHETIC` |
| Predicate-error rows on an immediate fire | Real context, origin `LOCAL` (unlabelled) | Same | Labelled | Needs an `is_synthetic` flag threaded through the predicate-failure path |
| New machinery | None; the builder stops nulling the context | Less: removes a flag and a constant | A payload field on every event | A threaded flag plus topic normalization |
| What peers do | NetDaemon `WithCurrent` and Node-RED "output on connect" reuse the real current state and its context; Node-RED and pyscript keep a call-side flag | AppDaemon and NetDaemon rely on `old_state` being absent | No peer marks the payload | No peer fabricates a context |
| Handler-visible change | `event.payload.context` becomes real; `event.topic` loses the entity suffix | Same | Same plus the new field | None |

**Recommendation:** A. `make_synthetic_state_event` builds `HassContext` from `current_state["context"]` and uses topic `Topic.HASS_EVENT_STATE_CHANGED`, so every consumer of the event records honest data. `build_execution_record` keeps origin `HASSETTE_SYNTHETIC` for `cmd.is_synthetic` but stops nulling the context id. The only unlabelled case is a raising `where=` during an immediate fire, and that row's context is real and its old value NULL. #3677's pickup should note that an immediate-fire row's context can match the API write that set the current value, so `caused_by` would point at it.
**Pick B instead if** you want less code and accept immediate-fire rows looking like ordinary `LOCAL` changes. **Pick C instead if** every consumer must label synthetic events from the event alone. **Pick D instead if** this PR should stay away from the synthetic-event factory.
**Reversibility:** easy (pre-V1; handler-visible `event.topic` and `context` on immediate fires)
**Ratified:** Chose building the synthetic event from the cached state's real context and the base state-changed topic while keeping the command-side `HASSETTE_SYNTHETIC` origin label, over dropping the label, adding a payload marker, or working around the fake event per consumer, so no row carries a fabricated context and every event kind has one topic shape, as NetDaemon and Node-RED do, accepting that predicate-error rows on an immediate fire are unlabelled and that handlers see a changed `event.topic` and a real context on immediate fires.

### D8: Does a delayed fire record the triggering event or the state at fire time?

**Situation:** a duration listener's invoke function closes over the event that started the hold; the fire-time recheck builds a throwaway synthetic event used only for `hold_matches`, which never reaches the record (`src/hassette/bus/duration_hold.py`). Debounced listeners likewise fire with the event they were given. So the recorded values can be N seconds older than `execution_start_ts`.

**Deciding factor:** the row describes the same event the handler received.

| | A: record the triggering event, documented | B: record fire-time state from the recheck |
|---|---|---|
| Matches the handler's `event` argument | Yes | No |
| Matches state at fire time | No | Yes |
| Code change | One docs sentence | A new path through duration hold |
| What peers do | Home Assistant's `for:` and pyscript's `state_hold` fire with the original event's context | unknown |

**Recommendation:** A, with one sentence in `docs/pages/core-concepts/database-telemetry.md` saying duration and debounced rows show the triggering event, not the state at fire time.
**Pick B instead if** you mostly use these rows to confirm state when the handler actually ran.
**Reversibility:** easy
**Ratified:** Chose recording the event that started the hold or debounce, documented in `database-telemetry.md`, over fire-time state from the recheck, so the row matches what the handler received as Home Assistant's `for:` does, accepting values that can be older than the run's start.

## Assumed

- Parent D6 holds: nullable event-summary columns on `executions`, not a side table or event JSON; `caused_by` belongs to #3677. Evidence: `design/specs/142-diagnostic-evidence/design.md` D6. The only sibling pickup, `146-debug-lines-failsafe-first`, doesn't touch executions.
- Parent D12 holds: the new columns age out with their execution row, with no new retention target. Evidence: parent D12.
- A Home Assistant event's `event_id` is its `context.id`, and `context.parent_id` is on the same `HassContext`. A Hassette-internal event (`HassettePayload`) has a uuid4 `event_id`, recorded as `trigger_context_id` as today, and no context, so its `trigger_parent_id` is NULL. Evidence: `HassPayload.__post_init__`, `HassContext` and `HassettePayload` in `src/hassette/events/base.py`.
- `HassPayload.entity_id` returns `data.entity_id` when the payload has one and `None` otherwise, so non-state events (such as `call_service`) record a NULL entity and values. Evidence: `src/hassette/events/base.py`.
- Any event with a `RawStateChangePayload` records old and new values from `old_state`/`new_state`: the `state` key, unless the listener's `EntityWatch.attribute` is set, in which case that attribute under `attributes`. A listener with no `EntityWatch` (a raw `bus.on` on a state-change topic) records state values. A missing state (entity created or removed) stores NULL. Evidence: `src/hassette/events/hass/hass.py`; `EntityWatch` is built only when an `entity_id` is passed (`src/hassette/bus/bus.py` `_subscribe`).
- The next migration number is `023`. Evidence: `src/hassette/migrations_sql/` ends at `022.sql` on `main` at `6eacd63d`.
- `GET /api/telemetry/execution/{execution_id}` and `HassetteClient.get_execution` already return an `Execution`, or `null` when no row has that id. Evidence: `src/hassette/web/routes/telemetry.py`, `client/src/hassette_client/client.py`.
- Seed scenarios and generated client/frontend types follow existing conventions for an executions column change. Evidence: parent Assumed; `scripts/seed_scenarios/`, `scripts/export_schemas.py`.

## Build

- [x] `refactor:` commit renaming `DurationConfig` to `EntityWatch` (D4), before the feature commit
- [ ] Implementation and tests committed
- [ ] Compat checks: run `check_wire_compat` and `uv run nox -s client_compat`; add each line they print to `tools/wire_compat_ignore.txt` / `tools/client_compat_ignore.txt` with a reason comment
- [ ] PR title uses `feat!:`; the body ends with exactly one `BREAKING CHANGE:` footer naming (1) the removed flat `Execution.trigger_context_id`/`trigger_origin`, which released clients now read as `None`, (2) `DurationConfig` → `EntityWatch` and `Listener.duration_config` → `Listener.entity_watch`, and (3) `hassette execution --json` returning an object
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

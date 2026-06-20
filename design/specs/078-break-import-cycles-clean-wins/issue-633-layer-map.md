# Revised layer map for #633 (draft comment — post manually)

> **Status: draft for posting to issue #633.** This is the layer-DAG revision produced by the
> #1079 clean-wins work (spec `078-break-import-cycles-clean-wins`). It is NOT auto-posted —
> review and post it to #633 yourself (e.g. `gh-issue` or the web UI) when ready.

The #1079 clean-wins refactor (PR for spec 078) landed three boundary rules in
`tools/check_module_boundaries.py` and, in doing so, validated and corrected the layer map
#633 proposed. Two corrections should feed back into #633's target DAG.

## Revised target DAG

```
L0  const, types                         leaves; no hassette imports
L1  models                               -> types, const
L2  config                               -> types, const, models
L3  utils, events, conversion,           -> L0-L2
    event_handling, schemas              utils -> events now one-directional (is_event_type
                                         moved to events/); schemas imports only types/const/utils
L4  resources                            -> L0-L3; shared base, BELOW the service group
L5  api, bus, scheduler, state_manager,  -> L0-L4, may use resources; not each other, not core
    task_bucket
L6  core                                 -> all below
L7  app                                  -> all below + core
L8  web, cli                             -> all below; web is launched by core's WebApiService
                                         (core -> web, one-directional; web must not import core)
L9  test_utils                           may import anything; production must not import it
```

## Two corrections vs #633's proposed map

1. **`resources` belongs BELOW the api/bus/scheduler service group, not beside it.** #633's map
   listed `api/bus/scheduler/state_manager/resources/task_bucket` as mutually independent peers.
   Reality: `api`, `bus`, `scheduler`, `state_manager`, and `task_bucket` all import `resources`
   (it's the shared `Resource`/`Service` base). So `resources` is its own layer (L4) below the
   service group (L5).

2. **`schemas` is a new L3 pure-data leaf.** The #1079 work extracted web-facing data types
   (`domain_models`, `telemetry_models`, the `app_registry` snapshots, `LiveCounts`, the telemetry
   query constants) out of `core` into a new `hassette.schemas` package that imports only
   `types`/`const`/`utils`. This is what broke the `web ↔ core` cycle.

## Now enforced (this PR)

`check_module_boundaries.py` now enforces four boundaries: `test_utils` isolation (pre-existing),
plus `api → core`, `utils → events`, `web → core`.

## Still blocked on an ADR (out of scope for #1079 clean wins)

Three runtime cycles import real `core` *logic*, not data, so breaking them needs a deliberate
relocate-vs-protocol-inversion decision (the inversion adds an abstraction layer that raises
reader-load — not an automatic win):

- `bus → core` — `bus/invocation.py` imports `core.commands.InvokeHandler` (depends on
  `bus.Listener` + `scheduler.ScheduledJob`, so it can't simply move down).
- `scheduler → core` — `scheduler.py` imports `core.scheduler_service.SchedulerService`.
- `state_manager → core` — `state_manager.py` imports `core.state_proxy.StateProxy`.

Full graph-level DAG/cycle enforcement (#633's headline check) can be turned on only after these
land. They are independent of #633 — if anything #633's DAG check is blocked by them, not the
reverse.

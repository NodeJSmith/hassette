---
topic: "How event-driven automation systems record why something did or did not run"
date: 2026-11-01
status: Draft
---

# Prior Art: recording why something did or did not run

## The Problem

Hassette's users open it after something happened that shouldn't have, or didn't happen when it should have. It records runs, but not events its listeners rejected, the service calls a run made, or connection and lifecycle history. This survey asks how peers record those things and how they bound the storage. Home Assistant's own Activity, Logs and traces are covered in `~/Dotfiles/design/research/2026-11-01-hassette-diagnostic-questions/ha-prior-art.md`.

## How We Do It Today

See `pipeline-evidence.md` in the same research directory. In short: `executions` rows and `log_records` exist; a rejected listener event leaves nothing but a DEBUG line, a default `call_service` is fire-and-forget with no record, and lifecycle state lives in memory or scattered log lines.

## Relevance to Us

- **Near-misses:** direct peers (AppDaemon, NetDaemon, EventBridge, Prefect, n8n) don't record them. Only HA does, since June 2026, and only for selected "interesting" cases. Recording every rejection goes beyond every peer, so its storage has to be justified by Hassette's own incidents: 8 of 13 were "didn't happen". The reusable ideas are HA's reason codes and separate bucket, and Kubernetes' dedupe-with-count.
- **Outbound calls:** Temporal, Step Functions and n8n record them per run, with limits on the container. HA's result frame returns a context id, which gives an exact join to later state changes, with a 5-second limit on the entity side. Failure frames carry no context.
- **Timeline:** Prefect and Kubernetes keep a separate event stream with a TTL. Airflow shows the risk: a transition that isn't wired in goes missing silently.
- **Debug capture:** no peer time-boxes it. Peers write debug output to a file or stdout, though; Hassette would write it to a DB table the size failsafe doesn't touch, which changes the trade-off.

## Recommendation

Copy reason codes, a separate bucket that can't evict real runs, and rollups with counts for near-misses. Record outbound calls as rows owned by the execution, and store HA's returned context id. Keep a small append-only event table with age-based retention for the timeline. The choices themselves are settled in `design/specs/` (Diagnostic Evidence ledger).

Coverage limits: AppDaemon and NetDaemon source wasn't audited for debug-level logging of filtered callbacks, and the URLs weren't live-verified.

# Prior art: how event-driven automation systems record why something did or did not run

Search tool: `exa-search` throughout (no fallback needed). HA items verified against raw files on `dev` (fetched 2026-11-01) and `gh` queries. Items marked [no source found] were looked for and not found. Note: dev's websocket_api now imports `probatio` where older HA used `voluptuous`; same schema shape.

## Sources Found

### HA core: helpers/trigger/entity_trigger.py + models.py + automation/entity.py + trace/models.py
- **URL**: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/trigger/entity_trigger.py ; .../helpers/trigger/models.py ; .../components/automation/entity.py ; .../components/trace/models.py
- **Type**: reference implementation
- **Key takeaway**: "Did not trigger" is a newly merged, opt-in mechanism (June 2026) that only some trigger classes use, with a machine-readable reason code plus data, stored in a separate size-limited bucket.
- **Relevance**: the only peer that records near-misses at all; design is directly copyable.

### HA PRs 174116 / 174636 / 175219 / 179608
- **URL**: https://github.com/home-assistant/core/pull/174116 (merged 2026-06-22, "Add optional callback did_not_trigger to triggers"); https://github.com/home-assistant/core/pull/174636 (merged, tests); https://github.com/home-assistant/core/pull/175219 (open, first/all behavior); https://github.com/home-assistant/core/pull/179608 (open, retention buckets by finish reason)
- **Type**: PRs
- **Key takeaway**: Near-miss reporting is still being rolled out trigger by trigger; per-outcome-class retention buckets are a proposal, not shipped.
- **Relevance**: shows HA itself judged "only report interesting cases" rather than every rejected event.

### Kubernetes: EventCorrelator (client-go) and event compression design
- **URL**: https://github.com/kubernetes/client-go/blob/master/tools/record/events_cache.go ; https://github.com/kubernetes/design-proposals-archive/blob/main/api-machinery/event_compression.md ; https://github.com/kubernetes/kubernetes/pull/16798/files ; TTL: https://github.com/kubernetes/kubernetes/blob/da53a247633/cmd/kube-apiserver/app/options/options.go
- **Type**: reference implementation / design doc
- **Key takeaway**: Client-side filter + aggregate + count; constants `maxLruCacheEntries = 4096`, `defaultAggregateMaxEvents = 10`, `defaultAggregateIntervalInSeconds = 600`, spam filter `defaultSpamBurst = 25`, `defaultSpamQPS = 1/300`. Server side: `--event-ttl` "Amount of time to retain events. Default is 1h."
- **Relevance**: the canonical bounded-storage answer for repetitive diagnostic records: dedupe-with-count, per-source token bucket, short TTL, "best effort" explicitly.

### AWS EventBridge monitoring + troubleshooting
- **URL**: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-monitoring.html ; https://repost.aws/knowledge-center/eventbridge-rules-troubleshoot ; https://aws.amazon.com/blogs/compute/enhanced-amazon-cloudwatch-metrics-for-amazon-eventbridge/
- **Type**: documentation
- **Key takeaway**: Metrics exist for matched events (`MatchedEvents`, per rule), `TriggeredRules`, `Invocations`, `FailedInvocations`, `DeadLetterInvocations`; there is no metric or record for an event that did NOT match a rule's pattern. The re-post troubleshooting guide answers "rule didn't fire" with "check CloudTrail that the event occurred and manually confirm it matches all fields in the event pattern", plus the doc says metrics are "best-effort... not meant to be a complete accounting".
- **Relevance**: confirms EventBridge does counters on the matched side only; non-match is diagnosed by the user comparing the event to the pattern by hand (there is a TestEventPattern API [not fetched]).

### Temporal event history
- **URL**: https://docs.temporal.io/references/events ; https://docs.temporal.io/workflow-execution/limits
- **Type**: documentation
- **Key takeaway**: "Activity Events... record each Activity Execution the Workflow schedules" (ActivityTaskScheduled/Started/Completed/Failed/TimedOut). History is "limited to 51,200 Events or 50 MB and will warn you after 10,240 Events or 10 MB."
- **Relevance**: outbound action records live inside the run's own history, so the link to the triggering run is structural, not a join key. Hard cap forces continue-as-new.

### Step Functions
- **URL**: https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-continue-new.html ; https://docs.aws.amazon.com/step-functions/latest/dg/concepts-view-execution-details.html ; https://docs.aws.amazon.com/step-functions/latest/dg/service-quotas.html
- **Type**: documentation
- **Key takeaway**: "Standard workflow executions have a maximum duration of one year and 25,000 events." Standard execution details are recorded; "the history of Express workflow executions are not" and require sending logs to CloudWatch. Service-quotas page mentions an adjustable "Execution history retention time" quota (value not captured in what I fetched; commonly 90 days [not confirmed here]).
- **Relevance**: two tiers: durable per-step history for slow workflows, nothing by default for high-rate ones.

### n8n execution data settings
- **URL**: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/executions ; https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/manage-execution-data
- **Type**: documentation
- **Key takeaway**: Defaults: `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE=336` (hours, 14 days), `EXECUTIONS_DATA_PRUNE_MAX_COUNT=10000`; separate `EXECUTIONS_DATA_SAVE_ON_ERROR` / `_ON_SUCCESS` / `_ON_PROGRESS`, overridable per workflow. Docs: "you can save only executions that result in an Error." Soft-delete every 60 min, hard-delete every 15 min after a 1 h buffer.
- **Relevance**: per-node run data is stored with the execution and pruned wholesale; retention is by age+count and by outcome class (save-on-error vs success).

### Prefect events and automations
- **URL**: https://reference.prefect.io/prefect/settings/models/server/events/ ; https://docs.prefect.io/v3/advanced/database-maintenance ; https://github.com/PrefectHQ/prefect/issues/16545
- **Type**: reference / documentation / issue
- **Key takeaway**: Events (state changes etc.) are stored with `retention_period` default `timedelta(days=7)`; the maintenance doc says events "can quickly become the largest" table. Issue #16545: a user's automation silently never fired against flow runs that met its conditions, with no way in the UI to see why.
- **Relevance**: Prefect keeps an append-only event stream (the activity timeline) with a TTL; it does not record why an automation did not fire.

### Airflow: audit log, job heartbeat, skip handling
- **URL**: https://airflow.apache.org/docs/apache-airflow/stable/security/audit_logs.html ; https://github.com/apache/airflow/blob/main/airflow-core/src/airflow/jobs/job.py ; https://github.com/apache/airflow/pull/6330 ; https://github.com/apache/airflow/pull/61932 ; https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/check-health.html
- **Type**: documentation / source / PRs
- **Key takeaway**: Audit log answers who/what/when for user actions; the `log` table also received task-state transitions (RUNNING, SUCCESS, SKIPPED, FAILED) which in Airflow 3 were accidentally dropped until PR 61932 re-added them. Scheduler liveness is a `Job` row with `latest_heartbeat` (updated in place, not append-only), surfaced by `/api/v2/monitor/health`. A caught `AirflowSkipException` was not logged at all until PR 6330 ("confusion due to no task skipping information being present in the logs").
- **Relevance**: SKIPPED is a first-class task state (a row), but the reason for the skip was historically unrecorded; liveness is a mutable heartbeat, not a history.

### Logging level control: Spring Boot, Envoy, HA, AppDaemon, Node-RED
- **URL**: https://docs.spring.io/spring-boot/reference/actuator/loggers.html ; https://www.envoyproxy.io/docs/envoy/latest/operations/admin ; https://www.home-assistant.io/actions/logger.set_level/ ; https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/helpers.py ; https://community.home-assistant.io/t/set-debug-in-appdaemon-yaml/233133 ; https://nodered.org/docs/user-guide/runtime/logging
- **Type**: documentation / source / forum
- **Key takeaway**: Spring actuator (`POST /actuator/loggers/<name>` with `configuredLevel`; `null` resets) and Envoy (`POST /logging?level=` or per component) change levels at runtime with no timer: they end only when someone resets or the process restarts. HA's logger helper has `LogPersistance.NONE/ONCE/PERMANENT`. AppDaemon 4 has per-app `log_level: DEBUG` in apps.yaml (config, applied on app reload). Node-RED log `level` is a settings-file value (restart); its `audit: false` flag is a separate switch.
- **Relevance**: nobody time-boxes by timer; "end of debug" is manual reset or restart, with HA's `ONCE` being the restart-scoped variant.

### AppDaemon / NetDaemon docs (negative evidence)
- **URL**: https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html ; https://github.com/home-assistant/appdaemon/issues/618 ; https://netdaemon.xyz/docs/user/troubleshooting/trouble_call_service/
- **Type**: documentation / issue
- **Key takeaway**: AppDaemon constraints ("prevent the callback from being executed unless certain conditions are met") and `old`/`new` filters have no documented record of a filtered-out callback; users debug by adding `self.log` in the callback (forum thread https://community.home-assistant.io/t/triggering-callbacks-on-attribute-change/598053). NetDaemon's troubleshooting page for CallService failures tells users to repeat the call in HA Developer Tools and check logs; no per-call persisted record.
- **Relevance**: the two direct peers do not bother.

## HA Source Verification

### (a) Which triggers record "Did not trigger", and how

Found. It is a small, new, opt-in mechanism, not general.

- Mechanism: a trigger may receive an optional `did_not_trigger` callback. `homeassistant/helpers/trigger/models.py`:
  > `class NotTriggeredInfo:` "Diagnostics describing why a trigger evaluated a change but did not fire. Passed by a trigger to its ``did_not_trigger`` reporter, the sibling of the action runner that is called - in certain interesting cases - when the trigger does not fire. ``reason`` is a stable, machine-readable code; the optional ``data`` carries the evaluated context for the trace."
- Recording: `homeassistant/components/automation/entity.py` `_handle_not_triggered`:
  > "Record a trace for a trigger that evaluated a change but did not fire. This is the diagnostic sibling of async_trigger: a trigger calls it - in certain interesting cases - when it does not run the action, so the user can see in the trace why the automation was not triggered."
  It makes `Context(parent_id=context.id)`, opens `trace_automation(..., not_triggered=True)`, appends a `TraceElement` with `set_result(**info.as_dict())` (`{"reason":..., "data":...}`) and calls `script_execution_set("not_triggered")`. It returns early if the automation is disabled.
- Storage: `homeassistant/components/trace/models.py`:
  > "Not-triggered traces (a trigger evaluated a change but did not fire) are counted and size-limited separately so they never evict actual run traces." (`TraceBuckets` has `runs` and `not_triggered` `LimitedSizeDict`s.) `DEFAULT_STORED_TRACES = 5` in `components/trace/const.py` ("Stored traces per script or automation").
- Which triggers: only `helpers/trigger/entity_trigger.py` (the newer class-based entity triggers) calls `report_not_triggered`. Code search for `NotTriggeredInfo` in core returns only: helpers/trigger/{models,__init__,entity_trigger}.py, components/automation/entity.py, plus tests. Reason codes seen: `threshold_entity_not_found`, `threshold_unit_not_supported`, `threshold_value_not_numeric` (threshold lookups), plus tracked-value problems. In the same file, several early returns do NOT report (e.g. `if not from_state or not to_state: return`, `if to_state.state in self._excluded_states: return`), i.e. HA reports "interesting" misconfiguration/value problems, not every rejected event. The legacy `homeassistant/components/homeassistant/triggers/{state,numeric_state,time}.py` have zero references. PR 175219 (open) would add first/all behavior misses.
- Docs: I did not re-open home-assistant.io/docs/automation/troubleshooting this pass; the prior-art file's claim that docs mention the feature stands, and the source shows it is limited as above.

### (b) context id on call_service result and later state_changed events

- Result returns the context. `homeassistant/components/websocket_api/commands.py` `handle_call_service`:
  > `context = connection.context(msg)`
  > `response = await hass.services.async_call(domain=msg["domain"], service=msg["service"], service_data=msg.get("service_data"), blocking=True, context=context, target=msg.get("target"), return_response=msg["return_response"])`
  > `result: dict[str, Context | ServiceResponse] = {"context": context}`
  > `connection.send_result(msg["id"], result)`
  So the result carries `{"context": {id, parent_id, user_id}}`.
- Caller cannot supply a context. Schema on dev:
  > `probatio.Required("type"): "call_service"`, `Required("domain"): str`, `Required("service"): str`, `Optional("target"): cv.ENTITY_SERVICE_FIELDS`, `Optional("service_data"): dict`, `Optional("return_response", default=False): bool`.
  And `websocket_api/connection.py`: `def context(self, msg): return Context(user_id=self.user.id)` (msg ignored). `parent_id` is always None; id is minted server-side.
- State events carry that context for entities directly targeted. `helpers/service.py` `_async_handle_entity_calls._with_context` does `entity.async_set_context(context)` before awaiting the entity method. `helpers/entity.py` writes state with `self._context` (`self.hass.states.async_set_internal(..., self._context, ...)`).
- Cases where state_changed will NOT carry it:
  1. Entity context expires: `CONTEXT_RECENT_TIME_SECONDS = 5  # Time that a context is considered recent` in `helpers/entity.py`; at write time `if self._context_set is not None and time_now - self._context_set > CONTEXT_RECENT_TIME_SECONDS: self._context = None`. A device push arriving more than 5 s after the call is written with no context (or a newer context). Any update before expiry, even an unrelated push, gets this context.
  2. Entities not in the target resolution (e.g. group members changed by the group entity, template/derived entities, integrations that update through a coordinator refresh) get their own or no context.
  3. `async_set_context` is only called on service-targeted entity objects; services that act via integration-level handlers (not entity services) do not call it, so state changes depend on that integration passing `context` through. [Inferred from reading the entity-service path; I did not audit integrations.]
- Not verified here: whether `hassette`'s `event_id` equals the HA event `context.id` (hassette-side question, out of scope).

### (c) Result timing and error codes

- Timing: handler hard-codes `blocking=True` and there is no schema field to change it, so `send_result` happens only after `async_call` returns, i.e. after the service handler finishes (for entity services, after each entity's service coroutine is awaited). For slow devices the WS result waits for that handler, not for the resulting state_changed. Result is sent, in the success case, also for `return_response=True` with `response` added.
- Error codes (`websocket_api/const.py` and handler):
  - `not_found` (`ERR_NOT_FOUND`): `ServiceNotFound` where the exact domain/service is missing: "Service {domain}.{service} not found."
  - `home_assistant_error`: any `HomeAssistantError` ("Error during service call to %s.%s: %s" is logged server-side; the message string is `str(err)`), and `ServiceNotFound` raised by a nested service call ("Service X called service Y which was not found.").
  - `service_validation_error` (`ERR_SERVICE_VALIDATION_ERROR`): `ServiceValidationError` ("Validation error: ...").
  - `invalid_format`: `probatio.Invalid` from the call.
  - `unknown_error`: any other exception.
  - Other codes in const.py that exist for the WS layer generally: `id_reuse`, `not_allowed`, `not_supported`, `unknown_command`, `unauthorized`, `timeout`, `template_error`.
  - Error frames carry `translation_domain`, `translation_key`, `translation_placeholders` (when the exception supplies them).
  - The error frame carries no context. So on failure the caller has no HA-side context id for the attempted call.

## Patterns Found

### Pattern 1: Opt-in near-miss records with a reason code, in a separate bucket

**Used by**: Home Assistant (helpers/trigger, automation traces, shipped mid-2026).
**How it works**: The component that evaluates a filter emits `(reason_code, small data dict)` only for "interesting" rejections. The record is a normal trace object flagged `not_triggered`, stored in its own size-limited bucket (default 5) so it cannot evict real runs. Many early-exit branches deliberately emit nothing.
**Strengths**: bounded, cheap, doesn't flood; reason codes are stable and machine-readable; the separate bucket solves the "noise evicts the run I want" complaint.
**Weaknesses**: coverage is partial and per-trigger; the user can't tell "evaluated and silent" from "not evaluated". Retention-by-outcome-class (PR 179608) is still a proposal.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/trigger/models.py ; https://github.com/home-assistant/core/pull/174116

### Pattern 2: Dedupe-with-count plus rate limit plus short TTL for repetitive diagnostics

**Used by**: Kubernetes Events (client-side EventCorrelator + apiserver TTL); HA's system_log (from the prior file).
**How it works**: Identical records (same source/object/reason) collapse into one row with `count`, `firstTimestamp`, `lastTimestamp`; many distinct variants within a window get aggregated into one "combined" record (10 within 600 s); a per-source token bucket (burst 25, refill 1 per 5 min) caps the long tail; an LRU of 4096 keys bounds client memory; server retention is 1 h by default.
**Strengths**: bounded no matter how chatty; keeps first and last time; stated "best effort".
**Weaknesses**: loses individual payloads; 1 h TTL is useless for after-the-fact questions a day later; the rate limit silently drops events past the burst.
**Example**: https://github.com/kubernetes/client-go/blob/master/tools/record/events_cache.go

### Pattern 3: Count-only on the match side, nothing on the miss side

**Used by**: AWS EventBridge (MatchedEvents, TriggeredRules, Invocations, FailedInvocations, DLQ metrics), Prefect automations (state-change event stream, no non-fire record), AppDaemon, NetDaemon, n8n triggers.
**How it works**: Operators learn that a rule ran and what happened to the target. For "why didn't it fire" they get a doc recipe: confirm the source event happened (CloudTrail), then manually compare to the pattern. Prefect issue 16545 shows a user with no UI path to explain a non-fire.
**Strengths**: trivially cheap; no storage question.
**Weaknesses**: the exact "should have run" question is unanswerable from the tool.
**Example**: https://repost.aws/knowledge-center/eventbridge-rules-troubleshoot ; https://github.com/PrefectHQ/prefect/issues/16545

### Pattern 4: Outbound calls recorded inside the run's own history

**Used by**: Temporal (Activity events), Step Functions Standard (per-state input/output in execution history), n8n (per-node run data stored with the execution).
**How it works**: Each outbound call is a scheduled/started/completed/failed record (or node run) appended to the single run record, so linkage to the trigger is containment, not a join. Limits are on the container: Temporal 51,200 events / 50 MB (warn at 10,240 / 10 MB); Step Functions 25,000 events; n8n prunes whole executions (14 days / 10,000, error-only saving available).
**Strengths**: one lookup answers "what did this run do and with what outcome"; outcome is a typed event.
**Weaknesses**: hard caps force restructuring (continue-as-new); high-rate flows (Step Functions Express) get no history by default; payloads dominate storage, hence save-on-error knobs.
**Example**: https://docs.temporal.io/references/events ; https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/manage-execution-data

### Pattern 5: Append-only event stream with TTL, separate from logs

**Used by**: Prefect (events, 7-day default retention, "can quickly become the largest table"), Kubernetes Events (1 h), Airflow (`log` table for user actions and, since 3.x fix, task transitions; no stated default prune besides `airflow db clean` [not verified]).
**How it works**: State/lifecycle changes are rows in their own table/API object with retention by age. Liveness is a different thing: Airflow's `Job.latest_heartbeat` is a single overwritten timestamp, exposed on a health endpoint, not a history.
**Strengths**: queryable timeline independent of log verbosity.
**Weaknesses**: easy to forget to wire a new transition into it (Airflow 3 regression, PR 61932); heartbeat can't tell you when a gap began.
**Example**: https://reference.prefect.io/prefect/settings/models/server/events/ ; https://github.com/apache/airflow/pull/61932

### Pattern 6: Runtime log-level endpoints with manual reset, no timer

**Used by**: Spring Boot actuator `/loggers`, Envoy `/logging`, istioctl proxy log level, HA `logger.set_level` and "Enable debug logging" (offers log download on disable), AppDaemon per-app `log_level`.
**How it works**: A privileged call sets a logger's level; reset is another call (Spring: `configuredLevel: null`) or process restart. HA's logger store has `persistence` of none/once/permanent (`once` is cleared at next load).
**Strengths**: no restart, scoped to one logger/component.
**Weaknesses**: forgotten debug levels persist. I found no peer with an auto-expiring debug window. [no source found for a timed variant]
**Example**: https://docs.spring.io/spring-boot/reference/actuator/loggers.html ; https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/helpers.py

### Pattern 7: Cross-system causation via a minted context id

**Used by**: Home Assistant (WS result returns `context`; state events carry it for ≤5 s).
**How it works**: See (b). The caller can record the returned id, but cannot choose it or set a parent, and the entity-side propagation window is 5 s.
**Strengths**: gives an exact join key from "I called X" to the state row when the integration cooperates.
**Weaknesses**: lossy for slow/derived/push-updated entities; no context on error frames.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/commands.py

## Anti-Patterns

- Silent skip: Airflow's skipped tasks logged no reason until PR 6330 ("confusion due to no task skipping information being present in the logs"): https://github.com/apache/airflow/pull/6330
- Transition missed by the audit table after an architecture change (Airflow 3 `ti_run`/`ti_update_state` not writing `log` rows): https://github.com/apache/airflow/pull/61932
- Real runs evicted by noise: HA's shared 5-slot trace bucket is the cited motive for the separate not-triggered bucket and for PR 179608: https://github.com/home-assistant/core/pull/179608
- Rate-limit drops without notice in k8s (spam filter) means a burst's tail disappears; accepted as "best effort": https://github.com/kubernetes/design-proposals-archive/blob/main/api-machinery/event_compression.md

## Emerging Trends

- HA moved from "no near-miss records" to opt-in reason-coded ones in 2026 (PR 174116, 175219), with outcome-bucketed retention under discussion (PR 179608). It is the only peer here moving in that direction.

## Gaps

- Not checked: Node-RED's debug node/audit setting contents beyond the docs snippet; NetDaemon source for any per-call record (docs show none); AppDaemon source for debug-level logging of filtered callbacks (no documentation found; [no source found]).
- Step Functions 90-day retention value is not confirmed from fetched text.

## Addendum: retention of debug lines

Question: do peers' choices about where debug lines live show something in Hassette's retention that makes per-app debug capture harder?

Measured on the live DB (read-only, 2026-11-01): 40 MB total, about 27 days of data. `log_records` table 7.1 MB (29,964 rows, none at DEBUG); `executions` table 9.8 MB, plus its indexes. 90 listeners, 75 jobs.

- **Keep debug out of the database:** HA (log file; "stays on if you restart Home Assistant once... After the next restart, it's off again", https://www.home-assistant.io/docs/configuration/troubleshooting/), Airflow (task log files, https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/logging-tasks.html), n8n (console or file, https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/logs).
- **Store and retain by level:** Seq ("Delete Debug and Verbose events after 48 hrs... Delete all remaining events at 30 days", https://datalust.co/docs/retention-policies), Loki (`retention_stream` by label selector, minimum 24h, https://grafana.com/docs/enterprise-logs/latest/manage/storage/retention/).
- **Store with no level handling:** Dagster ("Avoid including debug information if a large amount of run history will be maintained", https://dagster.io/docs/guides/log-debug/logging/python-logging; `event_logs` "grows without bounds", https://github.com/dagster-io/dagster/pull/33863, open), Prefect (logs in the DB with no automatic clean-up per a maintainer in https://github.com/PrefectHQ/prefect/discussions/16262; newer `db_vacuum` deletes logs with their flow runs, https://docs.prefect.io/v3/api-ref/python/prefect-server-services-db_vacuum).

Hassette's size-failsafe exemption for `log_records` (#2350) rests on the table being "structurally tiny", which stops being true once DEBUG is persisted. The failsafe would then delete executions to make room for debug lines it can't touch.

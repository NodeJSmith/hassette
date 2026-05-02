---
topic: "frontend exposure and interactivity for automation framework UIs"
date: 2026-05-02
status: Draft
---

# Prior Art: Frontend Exposure and Interactivity for Automation Framework UIs

## The Problem

Automation frameworks need to expose internal state to users for monitoring and debugging, but the design of *what* to show and *what to let users do* has major UX consequences. Show too little and users can't debug; show too much and users drown in noise. Make nothing interactive and users are stuck editing config files for every change; make everything editable and you create drift between code and runtime state.

The key tensions: read-only monitoring vs. interactive control, summary vs. detail, "what happened?" vs. "why?", and code-as-truth vs. UI-as-truth for configuration.

## How We Do It Today

Hassette's frontend is a **read-mostly monitoring UI** with limited control actions. Users can see: dashboard KPIs, app status grid, recent errors (with source_tier filtering), per-app handler/job lists with execution history, expandable tracebacks, and live logs. Interactive capabilities are limited to: start/stop/reload apps, expand/collapse detail panels, and filter by group/tier. There is no config editing, no manual job triggering, no execution replay. All configuration is code-only.

## Patterns Found

### Pattern 1: Tiered Detail Views (Progressive Disclosure)

**Used by**: Temporal (Compact/Timeline/Full History), n8n (summary → node-level data), Airflow (Grid View with expandable tasks)

**How it works**: Execution history is presented at multiple levels of detail. The default shows high-level summary (status, duration, outcome). A second tier shows per-step results with timing. The deepest tier shows raw event data or full payloads. Users choose their depth based on their current question.

Temporal implemented three named views explicitly: Compact (grouped event summaries for pattern recognition), Timeline (chronological with expandable details for "what happened when?"), and Full History (every event for deep debugging). The key insight: "what's happening now?" and "why did it fail?" require fundamentally different information density.

**Strengths**: Prevents information overload. Supports both quick-glance triage and deep investigation in one interface. Operators can scan for red at the summary level without wading through payloads.

**Weaknesses**: Requires careful design of tier boundaries. If the summary hides critical info, users always drill down (defeating the purpose). If the detail tier is too raw (e.g., unformatted JSON), it's only useful to framework developers.

**Example**: https://temporal.io/blog/the-dark-magic-of-workflow-exploration

### Pattern 2: Schema-Driven Manual Trigger Forms

**Used by**: Airflow (AIP-50 Params), Prefect (deployment parameters), GitHub Actions (workflow_dispatch inputs)

**How it works**: When a user wants to manually run an automation, the UI auto-generates a form from the automation's parameter schema. Types, defaults, descriptions, validation rules, and enum/select options come from the schema definition. The UI renders appropriate widgets (text inputs, dropdowns, date pickers, toggles) per type.

Airflow's AIP-50 was born from the pain of requiring users to write raw JSON to trigger DAGs. The solution: use DAG params (JSON Schema validation) to auto-generate forms. Airflow 3 makes this bidirectional. Prefect allows manual triggering and schedule modification directly from the UI.

For Pydantic-based frameworks, this is especially natural — the model IS the schema. AppConfig can drive both config display and trigger forms with zero extra work.

**Strengths**: Removes the "write JSON" barrier. Validation before execution prevents misconfigured runs. Descriptions educate users about parameters. Type-specific widgets prevent invalid input.

**Weaknesses**: Complex nested parameters are hard to represent in auto-generated forms. Schema must stay in sync with code. Power users sometimes prefer raw JSON for speed (offer both).

**Example**: https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-50+Trigger+DAG+UI+Extension+with+Flexible+User+Form+Concept

### Pattern 3: Execution Replay / Data Pinning

**Used by**: n8n (data pinning), Temporal (workflow reset), Home Assistant (community-requested)

**How it works**: The system captures input data from a previous execution and allows the user to re-trigger with that exact data. n8n calls this "data pinning" — copies execution data and pins it to the first node so users can modify and re-run. Temporal offers "workflow reset" that replays from a specific history point.

The HA community has explicitly requested this ("trigger automation using previous trace data") for debugging rarely-triggered automations. The core value: eliminates "how do I reproduce this?" entirely.

**Strengths**: Makes debugging deterministic. Allows iterative fixing without waiting for real events. Especially valuable for rarely-triggered automations where "wait for it to happen again" is impractical.

**Weaknesses**: Stale state — system may have changed since original execution. Re-running may have side effects (duplicate notifications, repeated service calls). Needs clear visual indication that this is a replay, not live.

**Example**: https://deepwiki.com/n8n-io/n8n-docs/2.4-execution-history-and-workflow-versioning

### Pattern 4: Real-Time Event Stream with Filtering

**Used by**: Node-RED (debug sidebar), Prefect (event feed), n8n (execution streaming)

**How it works**: A live feed of events streams into a panel, showing system activity in real time. Users filter by source (specific app/node), severity, or content. The feed has a fixed buffer (Node-RED: 100 messages) with automatic pruning. New entries appear with fade-in/highlight.

Node-RED's approach is notable: the debug sidebar is always visible alongside the flow editor, showing messages from any node with debug output enabled. Messages are expandable to inspect payloads. Filtering shows only selected sources while hidden messages still count toward the buffer.

**Strengths**: Immediate feedback loop ("I changed something, did it work?"). Low-latency issue discovery. Filtering prevents noise. Complements historical execution views with live awareness.

**Weaknesses**: High-frequency events can overwhelm the buffer. Users may become dependent on watching instead of using proper alerting. Without filtering, unusable in systems with many active automations.

**Example**: https://nodered.org/docs/user-guide/editor/sidebar/debug

### Pattern 5: Structured Error Context with Progressive Stack Traces

**Used by**: Sentry, Temporal, Prefect, general developer tooling

**How it works**: Errors display in two layers. The visible layer shows structured, human-readable context: error type, plain-language description of what went wrong, which handler/job/task failed, and what the user can do. The expandable layer shows the full stack trace for developers who need to trace the code path.

UX research consensus: error messages must answer three questions: What happened? Why? What can I do? Raw stack traces answer none of these. The pattern: structured summary (always visible) + technical details (on demand). Temporal shows exception message prominently with stack trace on expand. Prefect shows task failure reasons with structured metadata above the traceback.

**Strengths**: Serves both operators ("kitchen light failed because HA was unreachable") and developers ("connection timeout on line 47"). Reduces triage time. Preserves full debugging capability.

**Weaknesses**: Requires framework to capture structured error context at failure point, not just the exception. Generic messages ("An error occurred") are worse than raw traces. Maintaining quality error messages is ongoing work.

**Example**: https://www.pencilandpaper.io/articles/ux-pattern-analysis-error-feedback

### Pattern 6: Config Editing — Persisted, Not Ephemeral

**Used by**: Prefect (schedule editing), Airflow (connections/variables), Home Assistant (automations editor), n8n (node configuration)

**How it works**: Configuration is editable through the UI with real-time validation. Changes are persisted (not ephemeral). The UI enforces the same validation rules as the runtime. The industry consensus is clear:

- **Persisted**: "How this automation is configured" (schedules, parameters, thresholds)
- **Ephemeral**: "How this specific run was parameterized" (manual trigger overrides, one-off parameters)

Prefect allows modifying/pausing/deleting schedules from UI without touching code. HA persists automation edits to YAML. n8n validates config in real time and highlights errors before deploy.

**Strengths**: Removes the edit-file/restart/check-logs cycle. Validation prevents invalid deployments. Lowers barrier for non-developer operators.

**Weaknesses**: Drift risk between code-defined and UI-edited config ("two sources of truth" problem). Complex configs hard to represent in forms. Must handle concurrent edits. Can undermine code-as-source-of-truth principle.

**Example**: https://www.prefect.io/compare/airflow

### Pattern 7: One Page = One Decision

**Used by**: Observability dashboard best practices (Logz.io, Dash0, Grafana guidelines)

**How it works**: Each UI page answers a single operational question. "What's failing right now?" is one page. "How has this automation performed over time?" is another. "What are the details of this specific execution?" is yet another. Pages stay under 12 panels/widgets. Cross-linking allows navigation between related views without cramming everything into one screen.

The Logz.io analysis identifies "mixing decision types on one page" as a top mistake. When a page shows real-time status AND historical trends AND configuration AND recent errors, it becomes a wall of data answering no question well.

**Strengths**: Reduces cognitive load. Faster page loads. Clear mental model ("I go here for X, there for Y"). Easier to maintain and extend.

**Weaknesses**: Over-splitting creates "tab fatigue." Users may not know which page has their answer. Requires good navigation and cross-linking to prevent dead ends.

**Example**: https://logz.io/blog/top-10-mistakes-building-observability-dashboards/

### Pattern 8: Connected Trace Views (Cross-Automation Linking)

**Used by**: Temporal (event grouping), distributed tracing tools (Jaeger, Zipkin), requested by HA community

**How it works**: When one automation triggers another (or when an event propagates through multiple handlers), the UI shows these connections. Clicking an execution links to related executions it spawned or was spawned by. This creates a "trace tree" similar to distributed tracing spans.

HA users explicitly request this: "links from one automation's trace to related automation/script traces when one calls another." The lack of cross-referencing makes debugging chains difficult. Temporal groups related activities within a workflow execution. Distributed tracing tools (Jaeger) show parent-child span relationships.

**Strengths**: Makes event chains debuggable. Answers "what happened as a result of X?" without manual correlation. Turns isolated execution records into a connected story.

**Weaknesses**: Requires correlation IDs propagated through the system. Complex to implement if the bus doesn't already carry trace context. Can create overwhelming trace trees for heavily-connected systems.

**Example**: https://community.home-assistant.io/t/improved-traces-related-automations/888788

## Anti-Patterns

- **Raw JSON as Trigger Interface**: Airflow's pre-AIP-50 trigger UI required users to write JSON for manual runs. Most-requested improvement in the project's history. Schema-driven forms solved it completely. Source: https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-50+Trigger+DAG+UI+Extension+with+Flexible+User+Form+Concept

- **Fixed Low Trace Retention**: HA stores only 5 traces per automation with no configuration. For rarely-triggered automations, traces disappear before investigation. Multiple community threads with hundreds of votes request configurable retention. Source: https://community.home-assistant.io/t/make-traces-persist-longer-or-make-how-long-they-last-configurable/302348

- **Dashboard Overloading (>12 panels, mixed purposes)**: Cramming real-time status, historical trends, config, and error details onto one page means no single question is answered efficiently. 78% of platform engineers report alert fatigue partly from dashboard sprawl. Source: https://logz.io/blog/top-10-mistakes-building-observability-dashboards/

- **Siloed Execution Views Without Cross-Linking**: When automation A triggers automation B, no link exists between their traces. Debugging chains requires manually searching. This is the #1 UX complaint in event-driven automation systems. Source: https://community.home-assistant.io/t/improved-traces-related-automations/888788

## Emerging Trends

- **Progressive Disclosure as Table Stakes**: Temporal's three-tier view investment signals the industry has moved past "show everything or nothing." Users expect to control information density. This is now standard, not premium.

- **Schema-First UI Generation**: Airflow 3's params, Prefect's deployment parameters, and GitHub Actions' workflow_dispatch all converge on: define schema in code, get a UI for free. For Pydantic-based frameworks, this is a natural fit — the model IS the schema.

- **Execution Replay as Debugging Primitive**: n8n data pinning, HA community requests, Temporal reset all converge on replay. Capture inputs at execution start, allow re-execution. Especially valuable for event-driven systems where "wait for it to happen again" is impractical.

- **Connected Observability (Traces + Events + Metrics)**: Siloed views create cognitive overhead. The trend is unified navigation where clicking an error takes you to its trace, which links to the triggering event, which shows metric impact.

## Relevance to Us

Hassette's current UI is a solid **monitoring foundation** that already handles Pattern 7 (one page = one decision) reasonably well — dashboard for overview, app detail for debugging, sessions for lifecycle, logs for raw output. The expandable tracebacks implement a basic version of Pattern 5 (progressive error detail). Source-tier filtering (app vs. framework) is a nice touch not seen elsewhere.

**Where we align with best practice:**
- Expandable tracebacks (Pattern 5 — basic version)
- Source-tier filtering on errors
- Per-handler/job execution history with status, timing, duration
- App-level grouping with status overview
- One-page-one-purpose layout (Pattern 7)

**Gaps worth considering:**

1. **No manual trigger capability** — every surveyed framework offers "run now" from the UI. For hassette, this could mean: trigger a scheduled job immediately, or fire a synthetic event to test a listener. Pydantic AppConfig makes schema-driven trigger forms (Pattern 3) almost free.

2. **No execution replay** (Pattern 3/4) — can't re-run a handler with the event that triggered it. Since hassette captures listener invocations but not the triggering event data, this would need the "trigger context on invocations" column from the DB prior art survey.

3. **No cross-automation trace linking** (Pattern 8) — if App A's handler fires an event that triggers App B's listener, no UI connection exists. The bus already has this information; surfacing it in the UI would be a differentiator over HA.

4. **Error messages are raw** — tracebacks are available but there's no structured "what/why/action" summary layer (Pattern 5 full version). The `is_di_failure` flag is a step toward structured classification but doesn't translate to user-facing guidance yet.

5. **No config visibility or editing** (Pattern 6) — AppConfig values aren't visible in the UI at all. Even read-only display of current config would help debugging ("is this running with the right settings?"). Editable config is a bigger decision (code-as-truth vs. UI-as-truth).

6. **No live event stream** (Pattern 4) — the logs page partially serves this need, but a focused "what's happening right now on the bus?" view showing events flowing through handlers in real-time would be valuable for development/debugging.

**The config editability question specifically:**

The ecosystem consensus is:
- **Show config**: Always. Users need to verify what's running.
- **Edit config for operational parameters** (schedules, thresholds, enable/disable): Yes, persisted.
- **Edit config for structural changes** (which entities to watch, handler logic): No — this is code territory.
- **Ephemeral overrides**: Only for manual trigger parameters. "Run this once with X=5" is ephemeral; "change X to 5 going forward" is persisted.

For hassette specifically: AppConfig via Pydantic is well-suited to read-only display and potentially editable operational settings (env-var-backed fields). Structural changes (which bus subscriptions, which entities) should remain code-only.

## Recommendation

Hassette's UI is a competent monitoring tool but doesn't yet leverage its strongest architectural advantages (typed events on a bus, Pydantic config models, source_tier separation) for interactive debugging and control.

**Highest-impact additions, in order:**

1. **Config display** (read-only first) — show current AppConfig values per app. Almost zero effort since Pydantic serializes to JSON trivially. Huge debugging value ("is this running with the right threshold?").

2. **Manual job trigger** — "Run Now" button on scheduled jobs. The job already knows its handler and args; triggering it is a single API call. Consider schema-driven override forms for parameterized jobs.

3. **Structured error summaries** — transform the `is_di_failure` flag and error_type into user-facing guidance. "Dependency injection failed: [service] was not available" is far more useful than a raw traceback for the common case.

4. **Trigger context display** — when the DB schema adds trigger context to invocations (from the previous prior art survey's recommendation), surface it in the UI: "Triggered by: light.kitchen changed from off to on."

5. **Cross-app event flow** — the bus knows which events flow where. A view showing "Event X → handled by App A (200ms) and App B (45ms)" would be a significant differentiator over HA's siloed automation traces.

6. **Config editing** (deferred, design carefully) — only after establishing clear rules about what's editable vs. code-only. Schedules and thresholds are safe candidates; entity subscriptions and handler logic are not.

## Sources

### Reference implementations
- https://temporal.io/blog/the-dark-magic-of-workflow-exploration — Temporal execution history redesign
- https://temporal.io/blog/lets-visualize-a-workflow — Temporal timeline view
- https://docs.prefect.io/v3/api-ref/python/prefect-server-database-orm_models — Prefect ORM and UI patterns
- https://nodered.org/docs/user-guide/editor/sidebar/debug — Node-RED debug sidebar
- https://flowfuse.com/node-red/getting-started/programming/debugging-flows/ — Node-RED flow debugger

### Blog posts & writeups
- https://blog.logrocket.com/ux-design/ui-patterns-for-async-workflows-background-jobs-and-data-pipelines/ — UI patterns for async workflows
- https://logz.io/blog/top-10-mistakes-building-observability-dashboards/ — Dashboard anti-patterns
- https://www.dash0.com/blog/everything-is-connected-how-unified-ux-transforms-observability — Unified observability UX
- https://www.pencilandpaper.io/articles/ux-pattern-analysis-error-feedback — Error message UX patterns
- https://event-driven.io/en/property-sourcing/ — Property sourcing anti-pattern

### Documentation & standards
- https://cwiki.apache.org/confluence/display/AIRFLOW/AIP-50+Trigger+DAG+UI+Extension+with+Flexible+User+Form+Concept — Airflow schema-driven trigger forms
- https://docs.n8n.io/hosting/scaling/execution-data/ — n8n execution data management
- https://deepwiki.com/n8n-io/n8n-docs/2.4-execution-history-and-workflow-versioning — n8n execution history and replay

### Community feedback
- https://community.home-assistant.io/t/feature-request-feedback-script-automation-debugger-improvements/717104 — HA trace UX issues
- https://community.home-assistant.io/t/improved-traces-related-automations/888788 — HA cross-automation linking request
- https://community.home-assistant.io/t/make-traces-persist-longer-or-make-how-long-they-last-configurable/302348 — HA trace retention complaints

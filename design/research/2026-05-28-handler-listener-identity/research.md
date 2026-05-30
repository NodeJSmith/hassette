---
topic: "handler-listener-identity-for-idempotent-registration"
date: 2026-05-28
status: Draft
---

# Prior Art: Handler/Listener Identity for Idempotent Registration

## The Problem

When an event-driven framework supports hot-reload or restart, handlers registered in `initialize()` run again. The framework must decide whether the new registration is "the same handler" as one already registered, or a genuinely new handler. Get it wrong in one direction and you get duplicates (handler fires twice). Get it wrong in the other and you silently replace a handler that should coexist.

The question reduces to: **what defines "the same handler"?** The answer determines whether idempotent registration (`if_exists`) is simple or hard.

## How We Do It Today

Hassette uses two different identity models. Scheduled jobs have clean identity: `(app_key, instance_index, job_name)` where `job_name` is user-provided. `if_exists` already works for jobs. Listeners have fragile identity: `(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))` where `human_description` is a dynamically-computed predicate summary that can drift on refactoring. `name=` exists as an optional override but is rarely used. This asymmetry is the source of friction for implementing listener `if_exists` (#779).

## Patterns Found

### Pattern 1: User-Provided Stable Key

**Used by**: Django (dispatch_uid), Temporal (Workflow ID), Airflow (task_id), Kafka (consumer group ID), Ecotone (deduplication header)

**How it works**: The user provides a string identifier at registration time. The framework deduplicates by that key — if a registration with the same key exists, it either replaces (upsert) or rejects. Django's `dispatch_uid` was added specifically because Python object identity breaks on module re-import, causing duplicate signal receivers after reload. Temporal requires a Workflow ID and offers a configurable reuse policy (allow duplicate, reject, terminate-and-replace). Kafka consumer groups are identified by a required group ID string.

The key insight across all implementations: only the user knows what "the same handler" means in their domain. A handler watching `light.kitchen` with 10s debounce might be "the same" as one with 5s debounce (same purpose, different tuning) or "different" (distinct automations). The framework cannot decide.

**Strengths**: Survives restarts, reloads, and code changes. Simple to implement (dict keyed by string). Gives user full control. Enables upsert semantics naturally.

**Weaknesses**: Requires user to think about identity upfront. If forgotten (and no default), no deduplication. Key collisions between different handlers are silent bugs.

**Example**: [Django dispatch_uid](https://docs.djangoproject.com/en/6.0/topics/signals/)

### Pattern 2: Computed/Deterministic Identity

**Used by**: Celery (module.class_name for task registration), Temporal (recommended: derive from business inputs), Airflow (dag_id + task_id + execution_date)

**How it works**: Identity is computed deterministically from registration parameters. Celery tasks decorated with `@app.task` get a name auto-generated from module path + function name (e.g., `myapp.tasks.send_email`). Registration is idempotent because the same code always produces the same key.

**Strengths**: No manual key management. Naturally idempotent. Debuggable keys.

**Weaknesses**: Breaks when computation inputs change in identity-irrelevant ways (moving a function to a different module changes its Celery task name, breaking queued tasks). Assumes the framework picked the right parameters for identity.

**Example**: [Celery task naming](https://docs.celeryq.dev/en/stable/userguide/tasks.html)

### Pattern 3: Nuke and Rebuild (Epoch-Based)

**Used by**: AppDaemon (clear all callbacks on reload), RxJS/Angular (unsubscribe all on destroy), Node.js EventEmitter (removeAllListeners)

**How it works**: Instead of matching old handlers to new ones, the framework destroys all handlers for a scope (app, component) and re-registers from scratch. AppDaemon calls `terminate()`, clears all callbacks, then calls `initialize()`. Sidesteps identity entirely.

**Strengths**: Simple. No deduplication logic. No orphaned handlers. `initialize()` is the single source of truth.

**Weaknesses**: Loses accumulated state (invocation counts, timing data, rate limiter state). Cannot preserve continuity. Not suitable when handlers have persistent side effects (database records, telemetry) that need continuity.

**Example**: [AppDaemon App Guide](https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html)

### Pattern 4: Two-Tier Identity (Definition vs. Execution)

**Used by**: Celery (task name vs task_id), Temporal (Workflow ID vs Run ID), Airflow (task_id vs execution_date), Kafka (consumer group vs offset)

**How it works**: Two separate identity axes. Definition identity is stable and names the logical handler (Celery task name, Temporal Workflow ID). Execution identity is unique per invocation (Celery task_id UUID, Temporal Run ID). Definition identity answers "what handler is this?" — used for registration idempotency. Execution identity answers "which run?" — used for execution tracking.

**Strengths**: Clean separation. Each tier uses the identity strategy best suited to its purpose. Maps naturally to database schemas (registration table + invocation table).

**Weaknesses**: More complex mental model. FK relationships between tiers need careful design.

**Example**: [Temporal Workflow ID and Run ID](https://docs.temporal.io/workflow-execution/workflowid-runid)

### Pattern 5: Configuration-Defined Identity

**Used by**: Node-RED (node IDs in flow JSON), n8n (node IDs in workflow definition)

**How it works**: Identity comes from a persisted configuration file, not runtime registration. Node-RED nodes get IDs from the visual editor, stored in flow JSON. On startup, the framework creates runtime objects to match configuration. Declarative rather than imperative.

**Strengths**: Inherently stable. Versionable, diffable. Supports reconciliation.

**Weaknesses**: Requires a configuration layer. Doesn't work for programmatic-only registration (hassette's model).

**Example**: [Node-RED flow API](https://nodered.org/docs/api/admin/methods/get/flow/)

## Anti-Patterns

- **Silent duplicate registration**: EventEmitter allows duplicates without warning. Every restart adds another copy. Node.js added `setMaxListeners()` as a diagnostic aid, but it only warns. ([source](https://nodejs.org/api/events.html))

- **Object identity across reloads**: Using `id(func)` or `===` for identity breaks when modules are re-imported. Django added `dispatch_uid` specifically for this. ([source](https://docs.djangoproject.com/en/6.0/topics/signals/))

- **Random UUIDs as definition identity**: Makes idempotent registration impossible — each registration generates a new ID. Temporal explicitly warns against this. ([source](https://temporal.io/blog/idempotency-and-durable-execution))

- **Conflating identity with equality**: Comparing all registration parameters to determine "same handler" is fragile. A debounce change shouldn't create a new handler. User-provided keys make identity explicit rather than inferred. [no source found]

## Relevance to Us

Hassette already uses Pattern 4 (two-tier identity) for its database design — registration tables for definitions, invocation tables for executions. The gap is that the definition tier for listeners uses Pattern 2 (computed identity from handler+topic+predicate summary) while jobs use Pattern 1 (user-provided `job_name`). The predicate summary is the fragile part.

AppDaemon (Pattern 3, nuke and rebuild) is the closest domain analog but hassette can't use that pattern because telemetry records reference listener IDs. Nuking listeners would orphan invocation records.

The Django `dispatch_uid` story is the most instructive parallel: Django started with object identity, discovered it broke on reload, and added an optional user-provided key. Hassette is at the same crossroads — `name=` exists but is underused, and the computed fallback is fragile.

## Recommendation

**Converge on Pattern 1: user-provided `name` as required identity.**

Make `name` the primary identity for both listeners and jobs, and make it effectively required for listeners. The natural key becomes `(owner_key, instance_index, name)` for both tables — symmetric and stable.

**Why `name` must be required, not optional-with-fallback:** The most common hassette pattern is registering multiple handlers on the same entity for different states (e.g., `light.office` for "on" and "off"). An auto-generated name from `handler_method + topic` would collide immediately in this case, which is the majority of real-world usage. Framing `name=` as "optional, auto-generated if not provided" would mislead users — they'd hit collisions on their first non-trivial app and wonder what went wrong.

This matches the Temporal model (Workflow ID is required, not optional) rather than the Django model (dispatch_uid is optional). Hassette's use case is closer to Temporal's: persistent registration with telemetry, where identity must survive reloads, vs Django's ephemeral signal dispatch where duplication is annoying but not data-corrupting.

**What this gives:**
- Symmetric identity model for both listeners and jobs
- Stable across reloads (no predicate summary drift)
- Predicate description stays as metadata/documentation, exits the identity
- `if_exists` becomes straightforward: lookup by `(owner_key, instance_index, name)`, apply the collision policy
- Names appear in logs, CLI output, UI, and error messages — they're the human handle for "which handler"

**Migration path for existing apps:** Existing `name=` usage is sparse. Apps will need to add `name=` to all `on_state_change`/`on_attribute_change` calls. This is a breaking change, but the alternative (a fragile auto-generated fallback that fails on the most common pattern) is worse. The break is mechanical and the error message can be clear: "listener registration requires a name= parameter."

## Sources

### Reference implementations
- https://github.com/celery/celery/blob/main/celery/app/registry.py — Celery task registry (dict keyed by name)
- https://github.com/Olical/EventEmitter/issues/73 — EventEmitter duplicate listener discussion

### Documentation & standards
- https://docs.celeryq.dev/en/stable/userguide/tasks.html — Celery task naming and identity
- https://docs.temporal.io/workflow-execution/workflowid-runid — Temporal Workflow ID vs Run ID
- https://php.temporal.io/classes/Temporal-Common-IdReusePolicy.html — Temporal reuse policies
- https://docs.djangoproject.com/en/6.0/topics/signals/ — Django dispatch_uid
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon reload lifecycle
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon callback handles
- https://nodejs.org/api/events.html — Node.js EventEmitter (no deduplication)
- https://nodered.org/docs/api/admin/methods/get/flow/ — Node-RED flow persistence
- https://docs.n8n.io/workflows/workflow-id/ — n8n workflow and node identity
- https://rxjs.dev/guide/subscription — RxJS Subscription (disposable, no identity)
- https://developer.confluent.io/patterns/event-processing/idempotent-reader/ — Kafka consumer group identity
- https://docs.ecotone.tech/modelling/recovering-tracing-and-monitoring/resiliency/idempotent-consumer-deduplication — Ecotone deduplication

### Blog posts & writeups
- https://temporal.io/blog/idempotency-and-durable-execution — Temporal idempotency best practices
- https://medium.com/@chanon.krittapholchai/apache-airflow-useful-practices-idempotent-dag-6d52b1594704 — Airflow idempotent DAGs
- https://medium.com/codex/preventing-duplicate-signals-and-custom-signal-handling-in-django-13aea083f917 — Django duplicate signal prevention
- https://domaincentric.net/blog/event-sourcing-projection-patterns-deduplication-strategies — Event sourcing deduplication
- https://community.home-assistant.io/t/node-red-node-persistency-redeploy-or-restart/285673 — Node-RED persistence discussion

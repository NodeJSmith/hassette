---
topic: "Keying stored run history and registration rows to a user-named instance"
date: 2026-11-01
status: Draft
---

# Prior Art: Keying Stored History to a User-Named Instance

## The Problem

Issue #3098 re-keys the `listeners` and `scheduled_jobs` telemetry tables from the positional `(app_key, instance_index, ...)` to `(app_key, instance_name, ...)`. `executions` rows are FK children of those tables. The question is how much machinery this deserves: what happens to history when the identity changes or is first introduced, and what peers deliberately leave undone.

## How We Do It Today

Registration rows are upserted at startup on a natural key, so execution FKs survive restarts (`2026-04-06-stable-identity-upsert`). Reconciliation deletes absent rows with no history and retires those with history. Retention later deletes retired rows once their executions age out. Earlier briefs cover why this exists, but not renames, NULL keys, or backfill.

Three facts from the code bear on the survey:

- Framework resources have no instance name (`Resource.instance_name` returns `None`). SQLite treats NULLs as distinct, so a NULL name would make `ON CONFLICT` never fire and insert duplicates on every restart. A probe against SQLite 3.45.1 confirmed this.
- A live reload that changes one instance reconciles only that instance (`_create_instance_unlocked` passes `instance_index`). A rename reaches that path, so once scoping moves to the name, rows under the old name are outside the reconcile scope and stay active until a full app start.
- Migration 015 shows `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT` needs no table rebuild.

## Patterns Found

### Pattern 1: The name is the identity, and a rename orphans history

**Used by:** Airflow (`dag_id` primary key), Prefect (`Flow.name` unique), Dagster (asset key), AppDaemon (name from the YAML key). Celery Beat by inference from its name-keyed state; no rename documentation was found.

**How it works:** The user-chosen name keys the registration row and anchors run history. A rename creates a new row, and the old row keeps its history under the old name. Airflow's maintainer answer is to update `dag_id` in every table by hand if you want continuity.

**Strengths:** No migration code, and the behavior matches how the user wrote the config.

**Weaknesses:** Users complain (Prefect #8154, Airflow #13113, Dagster #9512), and none of the three ships a fix. Dagster's request has been open since 2022.

**Example:** https://github.com/apache/airflow/discussions/13113, https://github.com/dagster-io/dagster/issues/9512

### Pattern 2: Retire absent registrations and keep their history

**Used by:** Airflow (`is_stale`, with history kept), Hassette (`retired_at`).

**How it works:** Each pass upserts present registrations and marks absent ones stale. If the identity returns, its history comes back with it.

**Strengths:** A rename needs no logic of its own, because the old name is just an absent registration.

**Weaknesses:** Only works if absence is actually detected. Airflow #11901 is the complaint when it isn't: the old name stayed listed after a rename. The complaint was about clutter, not lost history.

**Example:** https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html, https://github.com/apache/airflow/issues/11901

### Pattern 3: Stable surrogate ID plus a mutable name

**Used by:** Home Assistant (`unique_id`, recorder `metadata_id`), n8n (`workflow_entity.id`).

**How it works:** History points at a surrogate and the name is an attribute, so a rename is one UPDATE.

**Strengths:** Renames keep history.

**Weaknesses:** Needs a rename event to hook, and Hassette's rename is a config edit that looks the same as removing one instance and adding another. Introducing it in Home Assistant took a multi-release background migration, which still left a gap for renames made before it finished.

**Example:** https://github.com/home-assistant/core/pull/89963

### Pattern 4: No per-registration persistence

**Used by:** AppDaemon, Home Assistant automation traces (the last 5 per automation), Temporal.

**How it works:** Registrations live in memory, and run history is a flat bounded record keyed by a string.

**Strengths:** The identity-migration problem doesn't exist.

**Weaknesses:** No registration view and no retired state, which Hassette's UI and CLI rely on. Airflow and Prefect do carry registration tables, so Hassette's isn't unusually heavy.

**Example:** https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adapi.py

### Pattern 5: SQLite NULL-in-unique-key workarounds

**Used by:** General SQLite practice, not a peer project.

**How it works:** SQLite has no `NULLS NOT DISTINCT`. The options are a unique expression index on `COALESCE(col, '')`, two partial unique indexes, or a `NOT NULL` column with a value validation makes impossible for users.

**Strengths:** The `NOT NULL` form keeps a plain unique index and a plain `ON CONFLICT` target.

**Weaknesses:** The first two complicate the upsert's conflict target. The third needs a value users can't choose, which D11's charset already guarantees.

**Example:** https://sqlite.org/lang_createindex.html, https://tech.maweki.de/nulls-not-distinct-in-sqlite-unique-indexes.html

## Anti-Patterns

- **Rename or merge tooling.** No peer ships it, including those with users asking for years (https://github.com/dagster-io/dagster/issues/9512).
- **Leaving the old identity visible.** This is what the Airflow complaint was actually about (https://github.com/apache/airflow/issues/11901).
- **Introducing a surrogate key as a migration side project** (https://github.com/home-assistant/core/pull/89963).

## Relevance to Us

D11 is Pattern 1, and `retired_at` is Pattern 2, so the design already matches the name-keyed peers. Reset-on-rename with no backfill is the norm, and building anything to carry history across would exceed what peers do.

The attention belongs on retiring rows under old names, since that is what users of the closest peer complained about, and on the framework-row key, which breaks upserts outright if done naively. A backfill and rename tooling are the overbuilding risks.

## Recommendation

Accept the history reset and document it, as Airflow, Prefect and Dagster do. Build no backfill, rename command or surrogate ID. Make sure a renamed instance's old rows retire without waiting for a full app start.

**Coverage gaps:**

- No peer evidence on system-owned rows in a named-key table. Home Assistant's exclusion of entities with no `unique_id` is the only analogue, so that choice rests on the SQLite sources and our own code.
- No peer has a positional field to compare, so keeping or dropping `instance_index` has no peer evidence.
- Nothing was found for pyscript.

## Sources

URLs were not live-verified after research.

### Reference implementations
- https://github.com/apache/airflow/blob/master/airflow-core/src/airflow/models/dag.py — `dag_id` primary key and `is_stale`
- https://github.com/PrefectHQ/prefect/blob/main/src/prefect/server/database/orm_models.py — `Flow.name` unique, runs as FK children
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adapi.py — name from the YAML key, callbacks in memory
- https://github.com/home-assistant/core/blob/5dcbc1d5/homeassistant/components/trace/util.py — flat per-key traces
- https://github.com/n8n-io/n8n/blob/master/docs/generated/postgres-schema/public.workflow_entity.md — surrogate workflow ID
- https://github.com/home-assistant/core/pull/89963 — retaining history on rename through `states_meta`
- https://github.com/home-assistant/core/pull/89557 — `states_meta`
- https://github.com/home-assistant/core/pull/52755 — statistics metadata update, accepting an incomplete first hour

### Issue threads and writeups
- https://github.com/apache/airflow/discussions/13113 — renaming a DAG and keeping history
- https://github.com/apache/airflow/issues/11901 — old `dag_id` remains in the UI
- https://github.com/PrefectHQ/prefect/issues/8154 — renaming flows and deployments
- https://github.com/dagster-io/dagster/issues/9512 — asset renaming, open since 2022
- https://github.com/dagster-io/dagster/discussions/17676 — no rename support
- https://community.home-assistant.io/t/wth-is-it-so-hard-to-control-how-old-entity-data-is-treated-when-you-rename-an-entity/810508 — user complaints about renames
- https://tech.maweki.de/nulls-not-distinct-in-sqlite-unique-indexes.html — NULLs in SQLite unique indexes

### Documentation and standards
- https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html — deactivation keeps history
- https://www.home-assistant.io/docs/automation/yaml — automation `id` enables rename and traces
- https://www.home-assistant.io/docs/automation/testing/ — last 5 traces per automation
- https://developers.home-assistant.io/docs/entity_registry_index/ — entities without `unique_id` aren't registered
- https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html — Beat schedule state
- https://docs.temporal.io/visibility — flat per-run records
- https://sqlite.org/lang_createindex.html — NULLs in unique indexes

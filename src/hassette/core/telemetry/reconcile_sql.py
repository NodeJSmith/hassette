"""SQL builders for reconciling listener and scheduled-job registrations and cleaning up removed apps."""

import json
from typing import Any

# The reconciliation query builders interpolate the table and its executions FK column directly into
# f-string SQL. Today every caller passes string literals, but this allowlist keeps that interpolation
# injection-safe if a non-literal value is ever passed in.
_HISTORY_FK = {"listeners": "listener_id", "scheduled_jobs": "job_id"}


def history_exists_sql(table: str) -> str:
    """Build the ``EXISTS`` predicate that says a row of ``table`` has execution history.

    Args:
        table: ``"listeners"`` or ``"scheduled_jobs"``.

    Returns:
        A boolean SQL expression referencing ``table.id``.
    """
    if table not in _HISTORY_FK:
        raise ValueError(f"Refusing to build SQL for unknown table: {table!r}")
    return f"EXISTS (SELECT 1 FROM executions WHERE {_HISTORY_FK[table]} = {table}.id)"


def instance_name_clause(instance_name: str | None) -> tuple[str, dict]:
    """Build the ``AND instance_name = :instance_name`` WHERE fragment and its bind param.

    Single-sources the instance-scoping fragment so every reconciliation SQL path (the
    ``build_delete_stale_jobs_query``/``build_retire_query`` builders) applies the same clause.

    Args:
        instance_name: The instance name to scope by, or ``None`` for no scoping.

    Returns:
        A ``(clause, params)`` tuple. Both are empty when ``instance_name`` is ``None``.
    """
    if instance_name is None:
        return "", {}
    return " AND instance_name = :instance_name", {"instance_name": instance_name}


def not_in_clause(live_ids: list[int]) -> tuple[str, dict]:
    """Build the ``AND id NOT IN (...)`` WHERE fragment and its bind params.

    Single-sources the live-ID exclusion fragment shared by ``build_delete_stale_jobs_query``,
    ``build_retire_query``, and ``build_clear_stale_job_timing_query``.

    Args:
        live_ids: IDs to exclude, bound as ``:id_0``, ``:id_1``, ...

    Returns:
        A ``(clause, params)`` tuple. Both are empty when ``live_ids`` is empty.
    """
    if not live_ids:
        return "", {}
    placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
    return f"AND id NOT IN ({placeholders})", {f"id_{i}": v for i, v in enumerate(live_ids)}


def build_delete_stale_jobs_query(
    app_key: str, live_ids: list[int], instance_name: str | None = None
) -> tuple[str, dict]:
    """Build a DELETE of the app's scheduled jobs that aren't in ``live_ids`` and have no execution history.

    There is no listener counterpart: reconciliation never deletes a listener row, because near-misses for
    it can still be buffered in memory, so the database alone can't say whether it has history.

    Args:
        app_key: The app key to scope the DELETE.
        live_ids: IDs to exclude from deletion.
        instance_name: When provided, additionally scopes the DELETE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    params: dict[str, Any] = {"app_key": app_key}
    live_ids_clause, live_ids_params = not_in_clause(live_ids)
    params.update(live_ids_params)

    instance_clause, instance_params = instance_name_clause(instance_name)
    params.update(instance_params)

    sql = f"""
        DELETE FROM scheduled_jobs
        WHERE app_key = :app_key{instance_clause}
          {live_ids_clause}
          AND NOT {history_exists_sql("scheduled_jobs")}
    """
    return sql, params


def build_retire_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    now: float,
    *,
    only_with_history: bool,
    instance_name: str | None = None,
) -> tuple[str, dict]:
    """Build an UPDATE that sets ``retired_at`` on the app's unretired rows that aren't in ``live_ids``.

    Args:
        table: Table to update (``"listeners"`` or ``"scheduled_jobs"``).
        app_key: The app key to scope the UPDATE.
        live_ids: IDs to exclude from retirement.
        now: Epoch timestamp for ``retired_at``.
        only_with_history: Retire only rows with execution history. Jobs pass True, since
            ``build_delete_stale_jobs_query`` deletes the rest; listeners pass False.
        instance_name: When provided, additionally scopes the UPDATE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    if table not in _HISTORY_FK:
        raise ValueError(f"Refusing to build SQL for unknown table: {table!r}")
    params: dict[str, Any] = {"app_key": app_key, "now": now}
    live_ids_clause, live_ids_params = not_in_clause(live_ids)
    params.update(live_ids_params)

    instance_clause, instance_params = instance_name_clause(instance_name)
    params.update(instance_params)

    history_clause = f"AND {history_exists_sql(table)}" if only_with_history else ""
    sql = f"""
        UPDATE {table} SET retired_at = :now
        WHERE app_key = :app_key{instance_clause}
          {live_ids_clause}
          AND retired_at IS NULL
          {history_clause}
    """
    return sql, params


def build_retire_unconfigured_instances_query(
    table: str, live_instances: list[tuple[str, str]], now: float
) -> tuple[str, dict]:
    """Build an UPDATE that sets ``retired_at`` on every unretired app-tier row of an instance that isn't live.

    Removed apps are never reconciled again, and reconciling a renamed instance only covers its new
    name, so this is the only thing that retires those rows. Framework registrations are
    ``source_tier = 'framework'`` and never match. Rows are retired whether or not they have
    execution history. Returns the ``app_key`` and ``instance_name`` of each
    retired row.

    Args:
        table: Table to update (``"listeners"`` or ``"scheduled_jobs"``).
        live_instances: Every ``(app_key, instance_name)`` in the current config or running.
        now: Epoch timestamp for ``retired_at``.

    Returns:
        A ``(sql, params)`` tuple.
    """
    if table not in _HISTORY_FK:
        raise ValueError(f"Refusing to build SQL for unknown table: {table!r}")
    sql = f"""
        UPDATE {table} SET retired_at = :now
        WHERE retired_at IS NULL
          AND source_tier = 'app'
          AND NOT EXISTS (
              SELECT 1 FROM json_each(:live_instances) live
              WHERE json_extract(live.value, '$[0]') = {table}.app_key
                AND json_extract(live.value, '$[1]') = {table}.instance_name
          )
        RETURNING app_key, instance_name
    """
    return sql, {"now": now, "live_instances": json.dumps(live_instances)}


def build_prune_removed_app_manifests_query(live_app_keys: list[str]) -> tuple[str, dict]:
    """Build a DELETE of every ``app_manifests`` row of an app that isn't live and that nothing references.

    Executions always belong to a listener or scheduled_job, so "no listeners, jobs, log records,
    blocking events or API writes for the app_key" also means no executions. ``app_key`` is the bare key in
    every table, so the match covers all instances. Returns the ``app_key`` of each
    deleted row.

    Args:
        live_app_keys: Every app key retention treats as present (``DatabaseRetentionMixin.live_app_keys``).

    Returns:
        A ``(sql, params)`` tuple.
    """
    sql = """
        DELETE FROM app_manifests
        WHERE app_key NOT IN (SELECT value FROM json_each(:live_keys))
          AND NOT EXISTS (SELECT 1 FROM listeners WHERE listeners.app_key = app_manifests.app_key)
          AND NOT EXISTS (SELECT 1 FROM scheduled_jobs WHERE scheduled_jobs.app_key = app_manifests.app_key)
          AND NOT EXISTS (SELECT 1 FROM log_records WHERE log_records.app_key = app_manifests.app_key)
          AND NOT EXISTS (SELECT 1 FROM blocking_events WHERE blocking_events.app_key = app_manifests.app_key)
          AND NOT EXISTS (SELECT 1 FROM api_writes WHERE api_writes.app_key = app_manifests.app_key)
        RETURNING app_key
    """
    return sql, {"live_keys": encode_app_keys(live_app_keys)}


def build_clear_stale_job_timing_query(live_job_ids: list[int]) -> tuple[str, dict]:
    """Build an UPDATE clearing ``next_run``/``fire_at``/``jitter`` on every job row not registered this session.

    Registration rewrites a live job's timing each session, so any row outside ``live_job_ids``
    (a removed app's job, or one not re-registered) still carries a previous session's timing.
    Rows whose timing is already all NULL are skipped.

    Args:
        live_job_ids: ``scheduled_jobs.id`` of every job registered this session. Empty clears every row.

    Returns:
        A ``(sql, params)`` tuple.
    """
    live_ids_clause, live_ids_params = not_in_clause(live_job_ids)
    sql = f"""
        UPDATE scheduled_jobs SET next_run = NULL, fire_at = NULL, jitter = NULL
        WHERE (next_run IS NOT NULL OR fire_at IS NOT NULL OR jitter IS NOT NULL)
        {live_ids_clause}
    """
    return sql, live_ids_params


def encode_app_keys(app_keys: list[str]) -> str:
    """Encode app keys for ``json_each``, which binds the whole variable-length list as one parameter."""
    return json.dumps(app_keys)

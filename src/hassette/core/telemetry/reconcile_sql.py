"""SQL builders for reconciling listener and scheduled-job registrations and cleaning up removed apps."""

import json
from typing import Any

# The reconciliation query builders interpolate ``table`` and ``history_fk`` directly into
# f-string SQL. Today every caller passes string literals, but an allowlist keeps that
# interpolation injection-safe if a non-literal value is ever passed in.
_RECONCILE_TABLES = frozenset({"listeners", "scheduled_jobs"})
_RECONCILE_FK_COLUMNS = frozenset({"listener_id", "job_id"})


def _assert_reconcile_identifiers(table: str, history_fk: str) -> None:
    if table not in _RECONCILE_TABLES or history_fk not in _RECONCILE_FK_COLUMNS:
        raise ValueError(f"Refusing to build SQL for unknown identifiers: table={table!r}, history_fk={history_fk!r}")


def instance_name_clause(instance_name: str | None) -> tuple[str, dict]:
    """Build the ``AND instance_name = :instance_name`` WHERE fragment and its bind param.

    Single-sources the instance-scoping fragment so every reconciliation SQL path (the
    ``build_delete_query``/``build_retire_query`` builders and the hand-written ``once=True``
    cleanup block) applies the same clause instead of five independent, driftable copies.

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

    Single-sources the live-ID exclusion fragment shared by ``build_delete_query``,
    ``build_retire_query``, ``build_clear_stale_job_timing_query``, and the hand-written
    ``once=True`` cleanup block.

    Args:
        live_ids: IDs to exclude, bound as ``:id_0``, ``:id_1``, ...

    Returns:
        A ``(clause, params)`` tuple. Both are empty when ``live_ids`` is empty.
    """
    if not live_ids:
        return "", {}
    placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
    return f"AND id NOT IN ({placeholders})", {f"id_{i}": v for i, v in enumerate(live_ids)}


def build_delete_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    extra_where: str = "",
    instance_name: str | None = None,
) -> tuple[str, dict]:
    """Build a DELETE query that removes rows not in ``live_ids`` without history.

    Args:
        table: Table to delete from (e.g. ``"listeners"``).
        app_key: The app key to scope the DELETE.
        live_ids: IDs to exclude from deletion.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).
        instance_name: When provided, additionally scopes the DELETE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key}
    live_ids_clause, live_ids_params = not_in_clause(live_ids)
    params.update(live_ids_params)

    instance_clause, instance_params = instance_name_clause(instance_name)
    params.update(instance_params)

    sql = f"""
        DELETE FROM {table}
        WHERE app_key = :app_key{extra_where}{instance_clause}
          {live_ids_clause}
          AND NOT EXISTS (
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


def build_retire_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    now: float,
    extra_where: str = "",
    instance_name: str | None = None,
) -> tuple[str, dict]:
    """Build an UPDATE query that sets ``retired_at`` for rows not in ``live_ids`` with history.

    Args:
        table: Table to update (e.g. ``"listeners"``).
        app_key: The app key to scope the UPDATE.
        live_ids: IDs to exclude from retirement.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        now: Epoch timestamp for ``retired_at``.
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).
        instance_name: When provided, additionally scopes the UPDATE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key, "now": now}
    live_ids_clause, live_ids_params = not_in_clause(live_ids)
    params.update(live_ids_params)

    instance_clause, instance_params = instance_name_clause(instance_name)
    params.update(instance_params)

    sql = f"""
        UPDATE {table} SET retired_at = :now
        WHERE app_key = :app_key{extra_where}{instance_clause}
          {live_ids_clause}
          AND retired_at IS NULL
          AND EXISTS (
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


def build_retire_unconfigured_instances_query(
    table: str, live_instances: list[tuple[str, str]], now: float
) -> tuple[str, dict]:
    """Build an UPDATE that sets ``retired_at`` on every unretired app-tier row of an instance that isn't live.

    Removed apps are never reconciled again, and reconciling a renamed instance only covers its new
    name, so this is the only thing that retires those rows. Framework registrations are
    ``source_tier = 'framework'`` and never match. Unlike ``build_retire_query``, rows are retired
    whether or not they have execution history. Returns the ``app_key`` and ``instance_name`` of each
    retired row.

    Args:
        table: Table to update (``"listeners"`` or ``"scheduled_jobs"``).
        live_instances: Every ``(app_key, instance_name)`` in the current config or running.
        now: Epoch timestamp for ``retired_at``.

    Returns:
        A ``(sql, params)`` tuple.
    """
    if table not in _RECONCILE_TABLES:
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

    Executions always belong to a listener or scheduled_job, so "no listeners, jobs, log records
    or blocking events for the app_key" also means no executions. ``app_key`` is the bare key in
    every table, so the match covers all instances. Returns the ``app_key`` of each
    deleted row.

    Args:
        live_app_keys: Every app key in the current config or with a running instance.

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

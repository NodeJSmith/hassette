"""SQL builders for reconciling listener and scheduled-job registrations."""

from typing import Any

# The reconciliation query builders interpolate ``table`` and ``history_fk`` directly into
# f-string SQL. Today every caller passes string literals, but an allowlist keeps that
# interpolation injection-safe if a non-literal value is ever passed in.
_RECONCILE_TABLES = frozenset({"listeners", "scheduled_jobs"})
_RECONCILE_FK_COLUMNS = frozenset({"listener_id", "job_id"})


def _assert_reconcile_identifiers(table: str, history_fk: str) -> None:
    if table not in _RECONCILE_TABLES or history_fk not in _RECONCILE_FK_COLUMNS:
        raise ValueError(f"Refusing to build SQL for unknown identifiers: table={table!r}, history_fk={history_fk!r}")


def _instance_index_clause(instance_index: int | None) -> tuple[str, dict]:
    """Build the ``AND instance_index = :instance_index`` WHERE fragment and its bind param.

    Single-sources the instance-scoping fragment so every reconciliation SQL path (the
    ``_build_delete_query``/``_build_retire_query`` builders and the hand-written ``once=True``
    cleanup block) applies the same clause instead of five independent, driftable copies.

    Args:
        instance_index: The instance index to scope by, or ``None`` for no scoping.

    Returns:
        A ``(clause, params)`` tuple. Both are empty when ``instance_index`` is ``None``.
    """
    if instance_index is None:
        return "", {}
    return " AND instance_index = :instance_index", {"instance_index": instance_index}


def _build_delete_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    extra_where: str = "",
    instance_index: int | None = None,
) -> tuple[str, dict]:
    """Build a DELETE query that removes rows not in ``live_ids`` without history.

    Args:
        table: Table to delete from (e.g. ``"listeners"``).
        app_key: The app key to scope the DELETE.
        live_ids: IDs to exclude from deletion.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).
        instance_index: When provided, additionally scopes the DELETE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key}
    if live_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
        params.update({f"id_{i}": v for i, v in enumerate(live_ids)})
        not_in_clause = f"AND id NOT IN ({placeholders})"
    else:
        not_in_clause = ""

    instance_clause, instance_params = _instance_index_clause(instance_index)
    params.update(instance_params)

    sql = f"""
        DELETE FROM {table}
        WHERE app_key = :app_key{extra_where}{instance_clause}
          {not_in_clause}
          AND NOT EXISTS (
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


def _build_retire_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    now: float,
    extra_where: str = "",
    instance_index: int | None = None,
) -> tuple[str, dict]:
    """Build an UPDATE query that sets ``retired_at`` for rows not in ``live_ids`` with history.

    Args:
        table: Table to update (e.g. ``"listeners"``).
        app_key: The app key to scope the UPDATE.
        live_ids: IDs to exclude from retirement.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        now: Epoch timestamp for ``retired_at``.
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).
        instance_index: When provided, additionally scopes the UPDATE to this instance so
            reconciling one instance does not affect sibling instances' rows.

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key, "now": now}
    if live_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
        params.update({f"id_{i}": v for i, v in enumerate(live_ids)})
        not_in_clause = f"AND id NOT IN ({placeholders})"
    else:
        not_in_clause = ""

    instance_clause, instance_params = _instance_index_clause(instance_index)
    params.update(instance_params)

    sql = f"""
        UPDATE {table} SET retired_at = :now
        WHERE app_key = :app_key{extra_where}{instance_clause}
          {not_in_clause}
          AND retired_at IS NULL
          AND EXISTS (
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params

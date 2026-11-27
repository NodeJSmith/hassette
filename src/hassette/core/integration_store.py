"""SQL for the ``integration_entities`` table (migrations ``027.sql`` to ``029.sql``).

Each function takes the write connection and runs on the database writer, so the caller submits it through
``DatabaseService.submit()``. The write connection autocommits, so the replace-set commit and the startup prune,
which each run several statements, open their own transaction and roll it back on any failure; a state update is a
single statement and needs none.
"""

import json
import typing
from collections.abc import Iterable
from dataclasses import dataclass

from hassette.core.database_sql import SQL_BEGIN, safe_rollback
from hassette.integration.declarations import Declaration, EntityState, IntegrationPlatform, encode_value

if typing.TYPE_CHECKING:
    import aiosqlite

    from hassette.core.database_sql import LoggerOwner

UPSERT_SQL = """
INSERT INTO integration_entities (
    app_key, instance_name, key, platform, name, default_entity_id, initial,
    unit, device_class, state_class, options, value, attributes, entity_category, icon
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (app_key, instance_name, key, platform) DO UPDATE SET
    name = excluded.name,
    default_entity_id = excluded.default_entity_id,
    initial = excluded.initial,
    unit = excluded.unit,
    device_class = excluded.device_class,
    state_class = excluded.state_class,
    options = excluded.options,
    value = excluded.value,
    attributes = excluded.attributes,
    entity_category = excluded.entity_category,
    icon = excluded.icon
"""

SELECT_ALL_SQL = """
SELECT app_key, instance_name, key, platform, name, default_entity_id, initial,
       unit, device_class, state_class, options, value, attributes, entity_category, icon
FROM integration_entities
ORDER BY app_key, instance_name, key, platform
"""


@dataclass(frozen=True, slots=True)
class StoredRow:
    """One ``integration_entities`` row as loaded: its declaration, and its value and attributes still encoded."""

    app_key: str
    instance_name: str
    declaration: Declaration
    value_text: str | None
    attributes_text: str | None


@dataclass(frozen=True, slots=True)
class PrunedInstance:
    """An instance whose rows the startup prune deleted, with how many there were."""

    app_key: str
    instance_name: str
    rows: int


def row_params(app_key: str, instance_name: str, declaration: Declaration, state: EntityState) -> tuple[object, ...]:
    """The upsert parameters for one declared entity and its state; a button stores no value or attributes."""
    is_button = declaration.platform is IntegrationPlatform.BUTTON
    return (
        app_key,
        instance_name,
        declaration.key,
        str(declaration.platform),
        declaration.name,
        declaration.default_entity_id,
        None if declaration.initial is None else int(declaration.initial),
        declaration.unit,
        declaration.device_class,
        declaration.state_class,
        None if declaration.options is None else json.dumps(list(declaration.options)),
        None if is_button else encode_value(state.value),
        None if is_button else json.dumps(dict(state.attributes)),
        declaration.entity_category,
        declaration.icon,
    )


async def prune_and_load(
    db: "aiosqlite.Connection", owner: "LoggerOwner", live: Iterable[tuple[str, str]]
) -> tuple[list[PrunedInstance], list[StoredRow]]:
    """Delete the rows of every instance not in ``live``, then load every remaining row.

    Returns:
        The pruned instances with their row counts, and the remaining rows.
    """
    live_set = set(live)
    try:
        await db.execute(SQL_BEGIN)
        cursor = await db.execute(
            "SELECT app_key, instance_name, COUNT(*) FROM integration_entities GROUP BY app_key, instance_name"
        )
        pruned = [
            PrunedInstance(app_key, instance_name, count)
            for app_key, instance_name, count in await cursor.fetchall()
            if (app_key, instance_name) not in live_set
        ]
        for instance in pruned:
            await db.execute(
                "DELETE FROM integration_entities WHERE app_key = ? AND instance_name = ?",
                (instance.app_key, instance.instance_name),
            )
        await db.commit()
    except BaseException:
        await safe_rollback(db, owner, "pruning integration entities")
        raise
    cursor = await db.execute(SELECT_ALL_SQL)
    rows: list[StoredRow] = []
    for row in await cursor.fetchall():
        try:
            rows.append(parse_row(row))
        except (ValueError, TypeError):
            # Skipped, not fatal: the instance's next commit rewrites the row as a new entity with its default state.
            app_key, instance_name, key, platform = row[:4]
            owner.logger.warning(
                "Skipped stored %s '%s' of app instance '%s/%s': it doesn't parse",
                platform,
                key,
                app_key,
                instance_name,
                extra={"app_key": app_key, "instance_name": instance_name, "key": key},
            )
    return pruned, rows


def parse_row(row: Iterable[typing.Any]) -> StoredRow:
    """Build a ``StoredRow`` from a ``SELECT_ALL_SQL`` row.

    Raises:
        ValueError: The platform or the stored options don't parse.
        TypeError: A column holds a non-text value where text is stored.
    """
    (
        app_key,
        instance_name,
        key,
        platform,
        name,
        default_entity_id,
        initial,
        unit,
        device_class,
        state_class,
        options,
        value,
        attributes,
        entity_category,
        icon,
    ) = row
    declaration = Declaration(
        key=key,
        platform=IntegrationPlatform(platform),
        name=name,
        default_entity_id=default_entity_id,
        entity_category=entity_category,
        icon=icon,
        initial=None if initial is None else bool(initial),
        unit=unit,
        device_class=device_class,
        state_class=state_class,
        options=None if options is None else parse_options(options),
    )
    return StoredRow(app_key, instance_name, declaration, value, attributes)


def parse_options(text: str) -> tuple[str, ...]:
    """Decode a stored enum sensor's options.

    Raises:
        ValueError: The text isn't a JSON list of strings.
    """
    options = json.loads(text)
    if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
        raise ValueError(f"stored options {text!r} aren't a list of strings")
    return tuple(options)


async def replace_instance_set(
    db: "aiosqlite.Connection",
    owner: "LoggerOwner",
    app_key: str,
    instance_name: str,
    entities: list[tuple[Declaration, EntityState]],
) -> None:
    """Replace an instance's declared set in one transaction: upsert each entity, delete every other row.

    A failure anywhere rolls the whole transaction back, leaving the previous set intact.
    """
    try:
        await db.execute(SQL_BEGIN)
        await db.executemany(
            UPSERT_SQL, [row_params(app_key, instance_name, declaration, state) for declaration, state in entities]
        )
        keep = {(declaration.key, str(declaration.platform)) for declaration, _ in entities}
        cursor = await db.execute(
            "SELECT key, platform FROM integration_entities WHERE app_key = ? AND instance_name = ?",
            (app_key, instance_name),
        )
        removed = [(key, platform) for key, platform in await cursor.fetchall() if (key, platform) not in keep]
        await db.executemany(
            "DELETE FROM integration_entities WHERE app_key = ? AND instance_name = ? AND key = ? AND platform = ?",
            [(app_key, instance_name, key, platform) for key, platform in removed],
        )
        await db.commit()
    except BaseException:
        await safe_rollback(db, owner, "committing integration entities")
        raise


async def update_state(
    db: "aiosqlite.Connection", app_key: str, instance_name: str, declaration: Declaration, state: EntityState
) -> int:
    """Write a switch's or sensor's value and attributes to its existing row.

    Returns:
        The number of rows updated: 0 when the row doesn't exist.
    """
    cursor = await db.execute(
        "UPDATE integration_entities SET value = ?, attributes = ? "
        "WHERE app_key = ? AND instance_name = ? AND key = ? AND platform = ?",
        (
            encode_value(state.value),
            json.dumps(dict(state.attributes)),
            app_key,
            instance_name,
            declaration.key,
            str(declaration.platform),
        ),
    )
    await db.commit()
    return cursor.rowcount

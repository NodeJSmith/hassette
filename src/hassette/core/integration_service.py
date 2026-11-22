"""IntegrationService: every app instance's declared buttons, switches and sensors, and their state (spec 157).

Holds the committed declarations and entity state in memory, backed by the ``integration_entities`` table, plus
the per-boot identifier and the hassette-wide revision counter. Every write (an instance's running-time commit,
a handle's ``set()``) runs as one job on the database writer that commits, then updates memory, then bumps the
revision, so memory never lags or reorders a committed write (spec 157 D10).
"""

import json
import typing
import uuid
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar

from hassette_wire import LogLevel

from hassette.core import integration_store
from hassette.core.database_service import DatabaseService
from hassette.events.hassette import IntegrationCommandEvent
from hassette.integration.declarations import (
    CommandDispatchResult,
    CommittedEntity,
    Declaration,
    EntityState,
    IntegrationPlatform,
    decode_value,
    default_state,
    resolve_state,
)
from hassette.integration.errors import IntegrationHandleClosedError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.schemas.app_config_shape import configured_instance_names

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.integration.integration import Integration

T = TypeVar("T")

InstanceKey: typing.TypeAlias = tuple[str, str]
"""``(app_key, instance_name)``."""

EntityKey: typing.TypeAlias = tuple[str, IntegrationPlatform]
"""``(key, platform)``, an entity's identity within its instance."""


@dataclass(frozen=True, slots=True)
class CommitCounts:
    """How a running-time commit changed an instance's set, compared with the set it replaced."""

    added: int
    kept: int
    removed: int


class IntegrationService(Resource):
    """Owns every instance's committed declarations and entity state, the revision, and command dispatch.

    Each write has three layers: the public entry point (``commit_instance``, ``set_state``) submits a ``*_job``
    through ``run_write``; the job decides what to write and updates memory; ``persist_*`` holds just the SQL.
    ``run_write``, ``prune_and_load`` and ``persist_*`` are the only database touch points, so the test harness's
    in-memory subclass overrides exactly those.
    """

    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]

    boot_id: str
    """Identifies this boot of hassette, so a reader can tell a restart from a revision that went backwards."""

    revision: int
    """Bumped on every committed entity state change and every declaration commit. Starts at 0 each boot."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.boot_id = uuid.uuid4().hex
        self.revision = 0
        self._entities: dict[InstanceKey, dict[EntityKey, CommittedEntity]] = {}
        self._owners: dict[InstanceKey, Integration] = {}

    @property
    def config_log_level(self) -> LogLevel:
        """Return the app handler's configured log level (``logging.app_handler``)."""
        return self.hassette.config.logging.app_handler

    async def on_initialize(self) -> None:
        """Prune the rows of instances absent from the config, then load the rest into memory."""
        pruned, rows = await self.prune_and_load(self.configured_instances())
        for instance in pruned:
            self.logger.warning(
                "Deleted the declared entities of app instance '%s/%s', which the config no longer has",
                instance.app_key,
                instance.instance_name,
                extra={"app_key": instance.app_key, "instance_name": instance.instance_name, "rows": instance.rows},
            )
        for row in rows:
            self._entities.setdefault((row.app_key, row.instance_name), {})[
                (row.declaration.key, row.declaration.platform)
            ] = CommittedEntity(row.declaration, self.restore_state(row))
        mark_ready(self, reason="integration entities loaded")

    def configured_instances(self) -> set[InstanceKey]:
        """Every ``(app_key, instance_name)`` the loaded config has, enabled or not, whatever ``--app`` filters."""
        return {
            (app_key, name)
            for app_key, manifest in self.hassette.config.apps.manifests.items()
            for name in configured_instance_names(manifest.app_config)
        }

    def restore_state(self, row: integration_store.StoredRow) -> EntityState:
        """Decode a loaded row's state; a value or attributes that don't parse give the default state instead.

        The default state is a sensor's unknown or a switch's ``initial``.
        """
        if row.declaration.platform is IntegrationPlatform.BUTTON:
            return EntityState()
        try:
            value = decode_value(row.declaration, row.value_text)
            attributes = json.loads(row.attributes_text) if row.attributes_text else {}
            if not isinstance(attributes, dict):
                raise ValueError(f"stored attributes {row.attributes_text!r} aren't a JSON object")
        except (ValueError, TypeError):
            self.logger.warning(
                "Stored state of '%s' (app instance '%s/%s') doesn't parse; it is restored as its default",
                row.declaration.key,
                row.app_key,
                row.instance_name,
                extra={"app_key": row.app_key, "instance_name": row.instance_name, "key": row.declaration.key},
            )
            return default_state(row.declaration)
        return EntityState(value=value, attributes=attributes)

    async def run_write(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run one write job on the database writer and return its result."""
        return await self.hassette.database_service.submit(coro)

    async def prune_and_load(
        self, live: set[InstanceKey]
    ) -> tuple[list[integration_store.PrunedInstance], list[integration_store.StoredRow]]:
        """Delete absent instances' rows and load the rest, on the database writer."""
        return await self.run_write(integration_store.prune_and_load(self.hassette.database_service.db, self, live))

    async def persist_instance_set(
        self, instance: InstanceKey, entities: list[tuple[Declaration, EntityState]]
    ) -> None:
        """Replace an instance's rows with ``entities`` in one transaction. Runs inside a write job."""
        await integration_store.replace_instance_set(self.hassette.database_service.db, self, *instance, entities)

    async def persist_state(self, instance: InstanceKey, declaration: Declaration, state: EntityState) -> None:
        """Write one entity's state to its existing row. Runs inside a write job.

        Raises:
            RuntimeError: The row doesn't exist.
        """
        updated = await integration_store.update_state(self.hassette.database_service.db, *instance, declaration, state)
        if updated == 0:
            raise RuntimeError(f"no stored row for {declaration.platform} {declaration.key!r} of {instance}")

    def committed(self, instance: InstanceKey, declaration: Declaration) -> CommittedEntity | None:
        """The committed entity for ``declaration``'s key and platform, or ``None``."""
        return self._entities.get(instance, {}).get((declaration.key, declaration.platform))

    def entities(self, app_key: str, instance_name: str) -> list[CommittedEntity]:
        """An instance's committed entities, in key order."""
        committed = self._entities.get((app_key, instance_name), {})
        return [committed[entity_key] for entity_key in sorted(committed)]

    async def commit_instance(
        self, owner: "Integration", declarations: list[Declaration], pending: Mapping[str, EntityState]
    ) -> CommitCounts:
        """Replace ``owner``'s instance's declared set and pending values, as one write job.

        Raises:
            Exception: The write failed; memory and the stored set are unchanged.
        """
        return await self.run_write(self.commit_job(owner, declarations, pending))

    async def commit_job(
        self, owner: "Integration", declarations: list[Declaration], pending: Mapping[str, EntityState]
    ) -> CommitCounts:
        """The running-time commit's write job: build the new set, write it, then update memory."""
        instance = owner.instance_key
        previous = self._entities.get(instance, {})
        entities = [
            (
                declaration,
                self.initial_state(
                    instance, declaration, previous.get((declaration.key, declaration.platform)), pending
                ),
            )
            for declaration in declarations
        ]
        await self.persist_instance_set(instance, entities)

        self._entities[instance] = {
            (declaration.key, declaration.platform): CommittedEntity(declaration, state)
            for declaration, state in entities
        }
        # A resource shut down while the write was in flight doesn't become the owner: the set stays, owned by
        # nobody, and a newer resource's claim made meanwhile is left alone.
        if not owner._closed:
            self._owners[instance] = owner
        self.revision += 1
        new_keys = set(self._entities[instance])
        old_keys = set(previous)
        counts = CommitCounts(
            added=len(new_keys - old_keys), kept=len(new_keys & old_keys), removed=len(old_keys - new_keys)
        )
        self.logger.info(
            "Committed the declared entities of app instance '%s/%s': %d added, %d kept, %d removed",
            *instance,
            counts.added,
            counts.kept,
            counts.removed,
            extra={
                "app_key": instance[0],
                "instance_name": instance[1],
                "added": counts.added,
                "kept": counts.kept,
                "removed": counts.removed,
            },
        )
        return counts

    def initial_state(
        self,
        instance: InstanceKey,
        declaration: Declaration,
        existing: CommittedEntity | None,
        pending: Mapping[str, EntityState],
    ) -> EntityState:
        """The state a committed entity starts with: its pending ``set()``, else its restored state, else its default.

        A restored value the new declaration rejects is reset to the default (a sensor's unknown), with a WARNING
        (spec 157 D12).
        """
        state, reset = resolve_state(
            declaration, pending.get(declaration.key), None if existing is None else existing.state
        )
        if not reset or existing is None:
            return state
        self.logger.warning(
            "Restored value %r of %s '%s' (app instance '%s/%s') doesn't fit its changed declaration; reset",
            existing.state.value,
            declaration.platform,
            declaration.key,
            *instance,
            extra={"app_key": instance[0], "instance_name": instance[1], "key": declaration.key},
        )
        return state

    def is_owner(self, owner: "Integration") -> bool:
        """Whether ``owner`` holds its instance's committed set: it committed last and hasn't released it.

        The authority for writes already submitted: ``set_job`` checks it when it runs, which catches a write
        queued by an old instance before a restart's new commit landed. ``Integration``'s phase is only its own
        early refusal, so it never submits a write it already knows will fail.
        """
        return self._owners.get(owner.instance_key) is owner

    def claim(self, owner: "Integration") -> None:
        """Make ``owner`` its instance's live owner without writing.

        For an instance that declared nothing and has nothing stored: it commits nothing, but is still running.
        """
        self._owners[owner.instance_key] = owner

    def release(self, owner: "Integration") -> None:
        """End ``owner``'s ownership of its instance, if it still holds it. Its committed state stays.

        Called when the owning ``Integration`` shuts down, and again when the lifecycle finishes stopping the
        instance (covering a walk-away, whose ``Integration`` never shuts down), so a handle used after that is
        rejected by ``set_job`` and a command for the instance is rejected by ``admit_command``.
        """
        if self.is_owner(owner):
            del self._owners[owner.instance_key]

    async def set_state(self, owner: "Integration", declaration: Declaration, state: EntityState) -> None:
        """Write one committed entity's state, as one write job.

        Raises:
            IntegrationHandleClosedError: ``owner`` doesn't hold its instance's committed set: its commit failed,
                or it has shut down.
            Exception: The write failed; memory is unchanged.
        """
        await self.run_write(self.set_job(owner, declaration, state))

    async def set_job(self, owner: "Integration", declaration: Declaration, state: EntityState) -> None:
        """``set()``'s write job: a no-op if nothing changed, else write the row, update memory, and publish it."""
        instance = owner.instance_key
        current = self.committed(instance, declaration)
        if not self.is_owner(owner) or current is None:
            raise IntegrationHandleClosedError(owner.instance_name, declaration.key)
        if current.state == state:
            return
        await self.persist_state(instance, declaration, state)
        entity = CommittedEntity(current.declaration, state)
        self._entities[instance][(declaration.key, declaration.platform)] = entity
        self.revision += 1
        # Awaited inside the write job, so /ws clients receive entity messages in revision order (spec 159 D2).
        # Without a web server (the app-testing harness) there is no RuntimeQueryService and no client to tell.
        # The public accessor raises when the service isn't wired, so read the slot, which core/ owns.
        runtime = self.hassette._runtime_query_service
        if runtime is not None:
            await runtime.publish_entity_state(self.boot_id, self.revision, instance, entity)

    async def dispatch_command(
        self, app_key: str, instance_name: str, key: str, platform: str, value: bool | None = None
    ) -> CommandDispatchResult:
        """Run the handler an instance declared for a button press or switch toggle, by publishing its command event.

        Admission is ``admit_command``'s. Nothing awaits between it and the publish's start.

        Args:
            app_key: The declaring app.
            instance_name: The declaring instance.
            key: The entity's key.
            platform: ``"button"`` or ``"switch"``.
            value: The commanded state for a switch; ``None`` for a button.

        Returns:
            ``DISPATCHED`` once published, else why nothing was.

        Raises:
            ValueError: ``platform`` isn't ``button`` or ``switch``, or ``value`` doesn't suit it.
        """
        resolved = IntegrationPlatform(platform)
        if resolved is IntegrationPlatform.SENSOR:
            raise ValueError("sensors take no commands")
        if resolved is IntegrationPlatform.SWITCH and not isinstance(value, bool):
            raise ValueError(f"a switch command needs a bool value, got {value!r}")
        if resolved is IntegrationPlatform.BUTTON and value is not None:
            raise ValueError(f"a button command takes no value, got {value!r}")

        admitted = self.admit_command(app_key, instance_name, key, resolved, value)
        if isinstance(admitted, CommandDispatchResult):
            return self.reject_command(admitted, app_key, instance_name, key, resolved)
        await self.hassette.send_event(admitted)
        return CommandDispatchResult.DISPATCHED

    def admit_command(
        self, app_key: str, instance_name: str, key: str, platform: IntegrationPlatform, value: bool | None
    ) -> IntegrationCommandEvent | CommandDispatchResult:
        """Decide whether a button press or switch toggle may run, and build its command event if so.

        The one place command admission lives, shared by ``dispatch_command`` and the test harness's press and
        toggle simulation. A command is admitted when the instance has a live owner (its commit landed and its
        ``Integration`` hasn't shut down) and ``key`` is committed on ``platform``. The owner map, not the app
        registry's status, decides "running": ownership ends in the same step as the instance's shutdown and
        can't be set by a commit that lands after it. A command arriving while the app's own ``on_shutdown`` runs
        is still admitted, as any bus event is until the app's listeners are removed.

        Returns:
            The command event, or ``NOT_RUNNING`` when the instance has no live owner, or ``NOT_DECLARED`` when it
            has no such committed entity.
        """
        instance = (app_key, instance_name)
        if instance not in self._owners:
            return CommandDispatchResult.NOT_RUNNING
        if (key, platform) not in self._entities.get(instance, {}):
            return CommandDispatchResult.NOT_DECLARED
        return IntegrationCommandEvent.create(
            app_key=app_key, instance_name=instance_name, key=key, platform=str(platform), value=value
        )

    def reject_command(
        self,
        result: CommandDispatchResult,
        app_key: str,
        instance_name: str,
        key: str,
        platform: IntegrationPlatform,
    ) -> CommandDispatchResult:
        """Log why a command was not dispatched, and return ``result``."""
        self.logger.warning(
            "Rejected a %s command for %r of app instance %r: %s",
            platform,
            key,
            f"{app_key}/{instance_name}",
            result,
            extra={"app_key": app_key, "instance_name": instance_name, "key": key, "reason": str(result)},
        )
        return result

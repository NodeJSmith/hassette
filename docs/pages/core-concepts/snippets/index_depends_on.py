from typing import ClassVar

from hassette.core.database_service import DatabaseService
from hassette.resources.base import Resource, Service


class CommandExecutor(Service):
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]

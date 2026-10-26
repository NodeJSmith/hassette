from typing import ClassVar

from hassette.core.database_service import DatabaseService
from hassette.resources.base import Resource
from hassette.resources.service import Service


class CommandExecutor(Service):
    required: ClassVar[bool] = True
    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]

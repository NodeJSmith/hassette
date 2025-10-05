import copy
import typing
import uuid
from logging import getLogger

from typing_extensions import deprecated

from hassette.core.enums import ResourceRole

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


class _HassetteBase:  # pyright: ignore[reportUnusedClass]
    class_name: typing.ClassVar[str]
    """Name of the class, set on subclassing."""

    role: typing.ClassVar[ResourceRole] = ResourceRole.BASE
    """Role of the resource, e.g. 'App', 'Service', etc."""

    unique_name: str
    """Unique name for the instance, combining class name and unique ID."""

    def __init_subclass__(cls) -> None:
        cls.class_name = cls.__name__

    def __init__(self, hassette: "Hassette", unique_name_prefix: str | None = None) -> None:
        """
        Initialize the class with a reference to the Hassette instance.

        Args:
            hassette (Hassette): The Hassette instance this resource belongs to.
            unique_name_prefix (str | None): Optional prefix for the unique name. If None, the class name is used.
        """

        self.unique_id = uuid.uuid4().hex
        """Unique identifier for the instance."""

        self.hassette = hassette
        """Reference to the Hassette instance."""

        prefix = unique_name_prefix or self.class_name
        self.unique_name = f"{prefix}.{self.unique_id[:8]}"
        """Unique identifier for the instance."""

        self.logger = getLogger(f"hassette.{self.unique_name}")
        """Logger for the instance."""

        self.logger.debug("Creating instance of '%s'", self.class_name)

    def __repr__(self) -> str:
        return f"<{self.class_name} unique_name={self.unique_name}>"

    def set_logger_to_level(self, level: typing.Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]) -> None:
        """Configure a logger to log at the specified level independently of its parent."""
        self.logger.setLevel(level)
        self.logger.propagate = False  # avoid parent's filters

        # Only add a handler if it doesn't already have one

        parent_logger = self.logger.parent
        while True:
            if parent_logger and not parent_logger.handlers:
                parent_logger = parent_logger.parent
            else:
                break

        if not self.logger.handlers and parent_logger and parent_logger.handlers:
            for parent_handler in parent_logger.handlers:
                # This assumes handler can be shallow-copied
                handler = copy.copy(parent_handler)
                handler.setLevel(level)
                self.logger.addHandler(handler)

    @deprecated("Use set_logger_to_level('DEBUG') instead")
    def set_logger_to_debug(self) -> None:
        """Configure a logger to log at DEBUG level independently of its parent."""
        self.set_logger_to_level("DEBUG")

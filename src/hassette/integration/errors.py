"""Errors raised by ``self.integration`` and its handles."""

from hassette.exceptions import HassetteError


class IntegrationDeclarationClosedError(HassetteError):
    """Raised by ``add_button``, ``add_switch`` or ``add_sensor`` after the instance's declarations were committed.

    An instance declares its entities while it initializes. The window closes when hassette commits the declared
    set, just before the instance is marked running, so the list Home Assistant sees is always complete.

    Attributes:
        key: The key the late call tried to declare.
        platform: The platform it tried to declare it on.
    """

    suggestion = "Declare every button, switch and sensor in on_initialize()."

    def __init__(self, key: str, platform: str) -> None:
        self.key = key
        self.platform = platform
        super().__init__(
            f"Cannot declare {platform} {key!r}: this instance's declarations were already committed. "
            "Entities can only be declared while the instance initializes."
        )


class IntegrationHandleClosedError(HassetteError):
    """Raised by a handle's ``set()`` or state read once the instance that declared it has stopped.

    Also raised when the instance's declarations failed to commit. Stops a task that outlived its instance (for
    example, across a reload) from reading or overwriting the state of the instance that replaced it.

    Attributes:
        instance_name: The instance that declared the handle.
        key: The handle's key.
    """

    def __init__(self, instance_name: str, key: str) -> None:
        self.instance_name = instance_name
        self.key = key
        super().__init__(f"Cannot set {key!r}: app instance {instance_name!r} has stopped")

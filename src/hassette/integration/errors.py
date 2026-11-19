"""Errors raised by ``self.integration`` and its handles."""

from hassette.exceptions import HassetteError
from hassette.integration.declarations import CommandDispatchResult


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


class IntegrationCommandRejectedError(HassetteError):
    """Raised when ``AppTestHarness`` simulates a button press or switch toggle that production would drop.

    Raised by ``simulate_button_press`` and ``simulate_switch_toggle``. Home Assistant's press or toggle is dropped
    when the app instance isn't running (it hasn't started, or has stopped) or when the instance's committed
    declarations have no such key on that platform.

    Attributes:
        reason: Why the command was rejected: ``CommandDispatchResult.NOT_RUNNING`` or ``NOT_DECLARED``.
        instance_name: The app instance the command targeted.
        key: The key the command targeted.
        platform: The platform the command targeted.
    """

    def __init__(self, reason: CommandDispatchResult, instance_name: str, key: str, platform: str) -> None:
        self.reason = reason
        self.instance_name = instance_name
        self.key = key
        self.platform = platform
        if reason is CommandDispatchResult.NOT_RUNNING:
            why = "the instance isn't running (it hasn't started or has stopped)"
        elif reason is CommandDispatchResult.NOT_DECLARED:
            why = "the instance declared no such entity"
        else:
            raise ValueError(f"{reason} is not a rejection reason")
        super().__init__(f"Cannot send {platform} command {key!r} to app instance {instance_name!r}: {why}")

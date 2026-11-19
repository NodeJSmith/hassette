"""IntegrationSimulationMixin — presses, toggles and declared-entity reads for ``AppTestHarness``."""

from typing import TYPE_CHECKING

from hassette.events import IntegrationCommandEvent
from hassette.integration.declarations import IntegrationPlatform
from hassette.testing._simulation import DEFAULT_SIMULATE_TIMEOUT

if TYPE_CHECKING:
    from hassette.app.app import App
    from hassette.core.integration_service import CommittedEntity
    from hassette.testing._harness import HassetteHarness


class IntegrationSimulationMixin:
    """Simulates Home Assistant pressing the app's declared buttons and toggling its switches.

    Depends on the host providing ``require_harness``, ``require_app`` and ``simulate_event``, which
    ``SimulationMixin`` gives ``AppTestHarness``.
    """

    if TYPE_CHECKING:

        def require_harness(self) -> "HassetteHarness": ...

        def require_app(self) -> "App": ...

        async def simulate_event(
            self, event: IntegrationCommandEvent, *, timeout: float = DEFAULT_SIMULATE_TIMEOUT
        ) -> IntegrationCommandEvent: ...

    @property
    def integration_entities(self) -> "list[CommittedEntity]":
        """The app's committed declarations, each with its current state, in key order."""
        app = self.require_app()
        return self.require_harness().integration_service.entities(app.app_key, app.instance_name)

    async def simulate_button_press(
        self, key: str, *, timeout: float = DEFAULT_SIMULATE_TIMEOUT
    ) -> IntegrationCommandEvent:
        """Press one of the app's declared buttons, as hass-hassette would, and wait for its handler.

        Args:
            key: The button's key.
            timeout: Maximum seconds to wait for the handler to complete.

        Returns:
            The dispatched command event, returned after the handler has drained.

        Raises:
            ValueError: The app declared no button with this key.
            DrainError: The handler raised.
            DrainTimeout: The drain did not finish within ``timeout``.
        """
        event = self.command_event(key, IntegrationPlatform.BUTTON, None)
        return await self.simulate_event(event, timeout=timeout)

    async def simulate_switch_toggle(
        self, key: str, on: bool, *, timeout: float = DEFAULT_SIMULATE_TIMEOUT
    ) -> IntegrationCommandEvent:
        """Toggle one of the app's declared switches, as hass-hassette would, and wait for its handler.

        The switch's state changes only if the handler calls ``set()``, as in production.

        Args:
            key: The switch's key.
            on: The commanded state, which the handler reads with ``D.SwitchCommand``.
            timeout: Maximum seconds to wait for the handler to complete.

        Returns:
            The dispatched command event, returned after the handler has drained.

        Raises:
            ValueError: The app declared no switch with this key.
            DrainError: The handler raised.
            DrainTimeout: The drain did not finish within ``timeout``.
        """
        event = self.command_event(key, IntegrationPlatform.SWITCH, on)
        return await self.simulate_event(event, timeout=timeout)

    def command_event(self, key: str, platform: IntegrationPlatform, value: bool | None) -> IntegrationCommandEvent:
        """Build the command event for one of the app's committed buttons or switches."""
        app = self.require_app()
        declared = {(entity.declaration.key, entity.declaration.platform) for entity in self.integration_entities}
        if (key, platform) not in declared:
            raise ValueError(f"app instance {app.instance_name!r} declared no {platform} with key {key!r}")
        return IntegrationCommandEvent.create(
            app_key=app.app_key, instance_name=app.instance_name, key=key, platform=str(platform), value=value
        )

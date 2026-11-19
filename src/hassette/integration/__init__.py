"""App-declared Home Assistant entities: ``self.integration`` and the handles it returns (spec 157)."""

from .declarations import IntegrationPlatform
from .errors import IntegrationDeclarationClosedError, IntegrationHandleClosedError
from .handles import IntegrationButton, IntegrationSensor, IntegrationSwitch
from .integration import Integration
from .sync import IntegrationSyncFacade

__all__ = [
    "Integration",
    "IntegrationButton",
    "IntegrationDeclarationClosedError",
    "IntegrationHandleClosedError",
    "IntegrationPlatform",
    "IntegrationSensor",
    "IntegrationSwitch",
    "IntegrationSyncFacade",
]

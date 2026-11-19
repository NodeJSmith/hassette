"""App-declared Home Assistant entities: ``self.integration`` and the handles it returns (spec 157)."""

from .declarations import CommandDispatchResult, IntegrationPlatform
from .errors import (
    IntegrationCommandRejectedError,
    IntegrationDeclarationClosedError,
    IntegrationHandleClosedError,
)
from .handles import IntegrationButton, IntegrationSensor, IntegrationSwitch
from .integration import Integration
from .sync import IntegrationSyncFacade

__all__ = [
    "CommandDispatchResult",
    "Integration",
    "IntegrationButton",
    "IntegrationCommandRejectedError",
    "IntegrationDeclarationClosedError",
    "IntegrationHandleClosedError",
    "IntegrationPlatform",
    "IntegrationSensor",
    "IntegrationSwitch",
    "IntegrationSyncFacade",
]

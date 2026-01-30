import logging

from .api import Api
from .app import App, AppConfig, AppSync, only_app
from .bus import Bus
from .config import HassetteConfig
from .const import ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
from .conversion import (
    STATE_REGISTRY,
    TYPE_REGISTRY,
    TypeConverterEntry,
    register_simple_type_converter,
    register_type_converter_fn,
)
from .core.core import Hassette
from .event_handling import accessors, conditions, dependencies, predicates
from .events import RawStateChangeEvent
from .models import entities, states
from .models.services import ServiceResponse
from .scheduler import Scheduler
from .task_bucket import TaskBucket

A = accessors
C = conditions
D = dependencies
P = predicates

logging.getLogger("hassette").addHandler(logging.NullHandler())

__all__ = [
    "ANY_VALUE",
    "MISSING_VALUE",
    "NOT_PROVIDED",
    "STATE_REGISTRY",
    "TYPE_REGISTRY",
    "A",
    "Api",
    "App",
    "AppConfig",
    "AppSync",
    "Bus",
    "C",
    "D",
    "Hassette",
    "HassetteConfig",
    "P",
    "RawStateChangeEvent",
    "Scheduler",
    "ServiceResponse",
    "TaskBucket",
    "TypeConverterEntry",
    "accessors",
    "conditions",
    "dependencies",
    "entities",
    "only_app",
    "predicates",
    "register_simple_type_converter",
    "register_type_converter_fn",
    "states",
]

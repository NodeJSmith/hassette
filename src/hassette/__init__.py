import logging

from . import events, models, topics
from .config import HassetteConfig
from .core import (
    Api,
    App,
    AppConfig,
    AppConfigT,
    AppSync,
    CronTrigger,
    HomeAssistantRestarted,
    IntervalTrigger,
    Not,
    Resource,
    ScheduledJob,
    Service,
    Subscription,
    only_app,
    predicates,
)
from .enums import ResourceRole, ResourceStatus
from .events import StateChangeEvent
from .models import entities, states
from .types import AsyncHandler, Handler, Predicate, TriggerProtocol

logging.getLogger("hassette").addHandler(logging.NullHandler())

__all__ = [
    "Api",
    "App",
    "AppConfig",
    "AppConfigT",
    "AppSync",
    "AsyncHandler",
    "CronTrigger",
    "Handler",
    "HassetteConfig",
    "HomeAssistantRestarted",
    "IntervalTrigger",
    "Not",
    "Predicate",
    "Resource",
    "ResourceRole",
    "ResourceStatus",
    "ScheduledJob",
    "Service",
    "StateChangeEvent",
    "Subscription",
    "TriggerProtocol",
    "entities",
    "events",
    "models",
    "only_app",
    "predicates",
    "states",
    "topics",
]

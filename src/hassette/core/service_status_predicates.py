"""Role filter for HASSETTE_EVENT_SERVICE_STATUS subscriptions.

Consumer: RuntimeQueryService (#1666), which forwards framework service status to the web UI.
"""

from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.types.enums import ResourceRole

SERVICE_ROLE_PATH = "payload.data.role"

IS_NOT_APP_ROLE = ~P.ValueIs(source=get_path(SERVICE_ROLE_PATH), condition=ResourceRole.APP)
"""Excludes APP-role resources from a service-status subscription.

Every ``Resource`` emits ``HASSETTE_EVENT_SERVICE_STATUS`` through the shared lifecycle
machinery, so an app's status transitions land on the same topic the framework's own do. This
keeps app transitions out of the web UI's framework-services stream, where apps (keyed by class
name, not instance) would collide; app status reaches the UI through ``app_status_changed``
instead.

Excludes APP rather than admitting SERVICE only, and the difference matters: several framework
resources are plain ``Resource`` subclasses (RESOURCE role), not ``Service``, and a SERVICE-only
filter would swallow their events. Negating APP also fails open on a missing or malformed role.
"""

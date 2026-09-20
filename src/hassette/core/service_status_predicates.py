"""Shared predicates for filtering HASSETTE_EVENT_SERVICE_STATUS subscriptions by role.

Every Resource -- apps included -- emits on this topic through the shared lifecycle
machinery, so a subscriber that only cares about framework-owned services must filter role
explicitly or an app's status transitions land on it too. Extracted here (rather than left
in service_watcher.py, its original home) because more than one subscriber needs it:
SessionManager's crash recording (#2153) and RuntimeQueryService's diagnostics panel (#1666),
alongside ServiceWatcher's own acting handlers.
"""

from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.types import ResourceRole

SERVICE_STATUS_PATH = "payload.data.status"
SERVICE_ROLE_PATH = "payload.data.role"

IS_NOT_APP_ROLE = ~P.ValueIs(source=get_path(SERVICE_ROLE_PATH), condition=ResourceRole.APP)
"""Excludes APP-role resources from a service-status subscription.

Every ``Resource`` emits ``HASSETTE_EVENT_SERVICE_STATUS`` through the shared lifecycle
machinery, so an app's status transitions land on the same topic the framework's own do. This
guards the acting handlers -- the ones that do something to the resource they observe (restart
it, take the process down, or record a session-level failure), as opposed to logging-only
handlers. One app's failure is not a framework failure.

Excludes APP rather than admitting SERVICE only, and the difference matters: several framework
resources are plain ``Resource`` subclasses (RESOURCE role), not ``Service``. A SERVICE-only
filter would swallow their events -- for instance, ``AppLifecycleService`` reaches
``handle_crash`` when ``bootstrap_apps()`` fails, and that crash must still count. Negating APP
also fails open on a missing or malformed role, matching the unfiltered behavior this narrows.
"""

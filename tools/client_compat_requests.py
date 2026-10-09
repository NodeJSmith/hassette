"""The requests ``tools/generate_client_compat_fixtures.py`` sends, each of whose responses becomes a fixture.

Success requests reach every JSON route; problem requests each answer one ``ProblemCode``; probe requests
catch the readiness and telemetry-status routes in their 503 state. Telemetry routes take identifiers from
the seeded database (:class:`SeedIds`). App actions, app config and source, and the job trigger read the
stub's live state, so they use the live apps' keys: the e2e fixtures' apps plus the ones
``tools/client_compat_live_state.py`` adds for states the e2e fixtures don't have, where each one's
docstring says which code or fixture it's for.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from client_compat_live_state import APP_KEY_BLOCKED_APP, APP_KEY_ESCAPING_APP, APP_KEY_UNREADABLE_APP, SeedIds
from hassette_wire import ProblemCode

from hassette.web.body_limit import MAX_REQUEST_BODY_BYTES
from tests.e2e.mock_fixtures.constants import (
    APP_KEY_BROKEN_APP,
    APP_KEY_MULTI_APP,
    APP_KEY_MY_APP,
    APP_KEY_NOSOURCE_APP,
    MANUAL_JOB_ID,
)

UNREGISTERED_JOB_ID = 999_999
"""A job id with no live registration, so triggering it answers ``job_not_registered``."""

AUTH_TOKEN = "client-compat-token"  # noqa: S105 - a fixed token for an in-process app, not a credential
"""Auth is on, as it is for a real client, so the auth layer's responses are in the fixtures too."""

UNKNOWN_EXECUTION_UUID = "00000000-0000-4000-8000-000000000000"
"""``/api/executions/{execution_id}`` requires a UUID; a scenario with no logged execution sends this one and
gets the empty result, so the route is still requested."""

ALL_TIERS = {"source_tier": "all"}
"""Routes that filter by source tier default to ``app``; ``all`` puts framework rows in the fixtures too."""

SINCE_EPOCH = {"since": "0"}
"""Makes app-grid compute its windowed parts: it fills ``activity_buckets`` and ``last_error`` only when given
``since``, so it's requested both with and without one. The window starts at the epoch, so it covers every
seeded row. Other routes' query params filter rows without changing the shape, so they get no such pair."""


@dataclass(frozen=True)
class FixtureRequest:
    """One request whose response becomes a fixture."""

    name: str
    method: str
    route: str
    """The route's path template. The ``not_found`` request uses a path no route serves."""
    params: Mapping[str, str | int] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] | None = None
    problem_code: ProblemCode | None = None
    """The code a problem request must answer with; ``None`` for a success request."""
    authenticated: bool = True
    """Send the bearer token, as hassette-client does when it has one."""
    probe: bool = False
    """The request must answer 503 with the route's own status model rather than a problem body: the probe
    routes (readiness, telemetry status) do this, and the released client parses that body as data. Written
    to the fixture as ``probe`` and passed to the release's ``interpret_response`` as ``status_model_on_503``.
    Mutually exclusive with ``problem_code``."""

    def __post_init__(self) -> None:
        if self.probe and self.problem_code is not None:
            raise ValueError(f"{self.name}: a request is either a problem or a probe request, not both")

    @property
    def path(self) -> str:
        return self.route.format(**{key: quote(str(value), safe="") for key, value in self.params.items()})

    @property
    def route_key(self) -> str:
        """``"<METHOD> <path template>"``, the name coverage reports use."""
        return f"{self.method} {self.route}"

    @property
    def is_success(self) -> bool:
        return self.problem_code is None and not self.probe


PROBLEM_REQUESTS = [
    FixtureRequest(
        "problem-invalid-app-key",
        "GET",
        "/api/apps/{app_key}",
        {"app_key": "not a key"},
        problem_code=ProblemCode.INVALID_APP_KEY,
    ),
    FixtureRequest(
        "problem-app-not-found",
        "GET",
        "/api/apps/{app_key}",
        {"app_key": "no_such_app"},
        problem_code=ProblemCode.APP_NOT_FOUND,
    ),
    FixtureRequest(
        "problem-instance-not-found",
        "POST",
        "/api/apps/{app_key}/instances/{index}/start",
        {"app_key": APP_KEY_MY_APP, "index": 99},
        problem_code=ProblemCode.INSTANCE_NOT_FOUND,
    ),
    FixtureRequest(
        "problem-app-blocked",
        "POST",
        "/api/apps/{app_key}/start",
        {"app_key": APP_KEY_BLOCKED_APP},
        problem_code=ProblemCode.APP_BLOCKED,
    ),
    FixtureRequest(
        "problem-action-failed",
        "POST",
        "/api/apps/{app_key}/reload",
        {"app_key": APP_KEY_BROKEN_APP},
        problem_code=ProblemCode.ACTION_FAILED,
    ),
    FixtureRequest(
        "problem-source-not-found",
        "GET",
        "/api/apps/{app_key}/source",
        {"app_key": APP_KEY_NOSOURCE_APP},
        problem_code=ProblemCode.SOURCE_NOT_FOUND,
    ),
    FixtureRequest(
        "problem-path-traversal",
        "GET",
        "/api/apps/{app_key}/source",
        {"app_key": APP_KEY_ESCAPING_APP},
        problem_code=ProblemCode.PATH_TRAVERSAL,
    ),
    FixtureRequest(
        "problem-source-unavailable",
        "GET",
        "/api/apps/{app_key}/source",
        {"app_key": APP_KEY_UNREADABLE_APP},
        problem_code=ProblemCode.SOURCE_UNAVAILABLE,
    ),
    FixtureRequest(
        "problem-job-not-registered",
        "POST",
        "/api/scheduler/jobs/{job_id}/trigger",
        {"job_id": UNREGISTERED_JOB_ID},
        problem_code=ProblemCode.JOB_NOT_REGISTERED,
    ),
    FixtureRequest(
        "problem-validation-failed",
        "GET",
        "/api/telemetry/executions",
        query={"limit": "not-a-number"},
        problem_code=ProblemCode.VALIDATION_FAILED,
    ),
    FixtureRequest(
        "problem-body-too-large",
        "PUT",
        "/api/logs/level",
        body={"logger": "x" * MAX_REQUEST_BODY_BYTES, "level": "DEBUG"},
        problem_code=ProblemCode.BODY_TOO_LARGE,
    ),
    FixtureRequest("problem-not-found", "GET", "/api/no-such-route", problem_code=ProblemCode.NOT_FOUND),
    FixtureRequest("problem-method-not-allowed", "DELETE", "/api/apps", problem_code=ProblemCode.METHOD_NOT_ALLOWED),
    FixtureRequest(
        "problem-not-authenticated",
        "GET",
        "/api/apps",
        authenticated=False,
        problem_code=ProblemCode.NOT_AUTHENTICATED,
    ),
]
"""Problem bodies don't depend on the seeded data, so they're requested against one scenario only."""

BOOTSTRAP_NOT_RELEASED_REQUEST = FixtureRequest(
    "problem-bootstrap-not-released",
    "POST",
    "/api/apps/{app_key}/start",
    {"app_key": APP_KEY_MY_APP},
    problem_code=ProblemCode.BOOTSTRAP_NOT_RELEASED,
)
"""Starting an app before app bootstrap is released. Sent to the ``hold_bootstrap`` stub variant
(``STUB_VARIANTS`` in the generator)."""

HEALTH_READY_UNAVAILABLE_REQUEST = FixtureRequest("health-ready-unavailable", "GET", "/api/health/ready", probe=True)
"""Readiness while app bootstrap is unreleased, so the system status isn't ``ok`` and the probe answers 503.
Sent to the ``hold_bootstrap`` stub variant."""

APP_GRID_DEGRADED_REQUEST = FixtureRequest("app-grid-degraded", "GET", "/api/telemetry/app-grid", query=SINCE_EPOCH)
"""App-grid with one enrichment query failing, so it answers 200 with that part ``None``. Sent to the
``fail_activity_buckets`` stub variant; :data:`SINCE_EPOCH` is what makes app-grid run that query."""

INTERNAL_ERROR_REQUEST = FixtureRequest(
    "problem-internal-error", "GET", "/api/apps", problem_code=ProblemCode.INTERNAL_ERROR
)
"""The app list with its runtime overlay raising an exception no handler maps. Sent to the
``break_runtime_overlay`` stub variant."""

TELEMETRY_UNAVAILABLE_REQUEST = FixtureRequest(
    "problem-telemetry-unavailable",
    "GET",
    "/api/telemetry/executions",
    problem_code=ProblemCode.TELEMETRY_UNAVAILABLE,
)
"""A telemetry query with telemetry unavailable. Sent to the shared app after its database connection is
closed, which is what makes telemetry unavailable."""

TELEMETRY_STATUS_UNAVAILABLE_REQUEST = FixtureRequest(
    "telemetry-status-unavailable", "GET", "/api/telemetry/status", probe=True
)
"""The telemetry-status probe with telemetry unavailable, so it answers 503. Sent after the database
connection is closed, like :data:`TELEMETRY_UNAVAILABLE_REQUEST`."""


def success_requests(ids: SeedIds) -> list[FixtureRequest]:
    """One request per JSON route, skipping routes that need an identifier ``ids`` lacks."""
    my_app = {"app_key": APP_KEY_MY_APP}
    my_app_instance = {"app_key": APP_KEY_MY_APP, "index": 0}
    multi_app = {"app_key": APP_KEY_MULTI_APP}
    logged_execution = {"execution_id": ids.logged_execution_id or UNKNOWN_EXECUTION_UUID}
    requests = [
        FixtureRequest("health", "GET", "/api/health"),
        FixtureRequest("health-live", "GET", "/api/health/live"),
        FixtureRequest("health-ready", "GET", "/api/health/ready"),
        FixtureRequest("apps", "GET", "/api/apps"),
        FixtureRequest("app-start", "POST", "/api/apps/{app_key}/start", my_app),
        FixtureRequest("app-stop", "POST", "/api/apps/{app_key}/stop", my_app),
        FixtureRequest("app-reload", "POST", "/api/apps/{app_key}/reload", my_app),
        FixtureRequest("app-instance-start", "POST", "/api/apps/{app_key}/instances/{index}/start", my_app_instance),
        FixtureRequest("app-instance-stop", "POST", "/api/apps/{app_key}/instances/{index}/stop", my_app_instance),
        FixtureRequest("app-instance-reload", "POST", "/api/apps/{app_key}/instances/{index}/reload", my_app_instance),
        FixtureRequest(
            "app-multi-instance-stop",
            "POST",
            "/api/apps/{app_key}/instances/{index}/stop",
            {**multi_app, "index": 1},
        ),
        FixtureRequest("app-config", "GET", "/api/apps/{app_key}/config", my_app),
        FixtureRequest("app-multi-config", "GET", "/api/apps/{app_key}/config", multi_app),
        FixtureRequest("app-source", "GET", "/api/apps/{app_key}/source", my_app),
        FixtureRequest("logs-recent", "GET", "/api/logs/recent", query=ALL_TIERS),
        FixtureRequest("log-level", "PUT", "/api/logs/level", body={"logger": "hassette", "level": "DEBUG"}),
        FixtureRequest("execution-logs", "GET", "/api/executions/{execution_id}", logged_execution),
        FixtureRequest("bus-listeners", "GET", "/api/bus/listeners", query=ALL_TIERS),
        FixtureRequest("config", "GET", "/api/config"),
        FixtureRequest("telemetry-status", "GET", "/api/telemetry/status"),
        FixtureRequest("blocking-findings", "GET", "/api/telemetry/blocking/findings"),
        FixtureRequest("blocking-unattributed", "GET", "/api/telemetry/blocking/unattributed"),
        FixtureRequest("executions", "GET", "/api/telemetry/executions"),
        FixtureRequest("app-grid", "GET", "/api/telemetry/app-grid"),
        FixtureRequest("app-grid-since", "GET", "/api/telemetry/app-grid", query=SINCE_EPOCH),
        FixtureRequest("scheduler-jobs", "GET", "/api/scheduler/jobs", query=ALL_TIERS),
        FixtureRequest("job-trigger", "POST", "/api/scheduler/jobs/{job_id}/trigger", {"job_id": MANUAL_JOB_ID}),
    ]
    if ids.app_key is not None:
        app = {"app_key": ids.app_key}
        requests += [
            FixtureRequest("app", "GET", "/api/apps/{app_key}", app),
            FixtureRequest("app-health", "GET", "/api/telemetry/app/{app_key}/health", app, ALL_TIERS),
            FixtureRequest("app-listeners", "GET", "/api/telemetry/app/{app_key}/listeners", app, ALL_TIERS),
            FixtureRequest("app-activity", "GET", "/api/telemetry/app/{app_key}/activity", app, ALL_TIERS),
            FixtureRequest("app-jobs", "GET", "/api/telemetry/app/{app_key}/jobs", app, ALL_TIERS),
            FixtureRequest("app-blocking", "GET", "/api/telemetry/app/{app_key}/blocking", app),
        ]
    if ids.multi_app_listed:
        requests.append(FixtureRequest("app-live", "GET", "/api/apps/{app_key}", multi_app))
    if ids.listener_id is not None:
        listener = {"listener_id": ids.listener_id}
        requests.append(
            FixtureRequest("listener-executions", "GET", "/api/telemetry/listener/{listener_id}/executions", listener)
        )
    if ids.job_id is not None:
        requests.append(
            FixtureRequest("job-executions", "GET", "/api/telemetry/job/{job_id}/executions", {"job_id": ids.job_id})
        )
    if ids.execution_id is not None:
        execution = {"execution_id": ids.execution_id}
        requests.append(FixtureRequest("execution", "GET", "/api/telemetry/execution/{execution_id}", execution))
    if ids.failed_execution_id is not None:
        failed = {"execution_id": ids.failed_execution_id}
        requests.append(FixtureRequest("execution-failed", "GET", "/api/telemetry/execution/{execution_id}", failed))
    return requests

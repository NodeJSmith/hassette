"""The typed async client for hassette's HTTP API."""

import aiohttp
from hassette_wire import (
    ActionResponse,
    ActivityFeedEntry,
    AppAction,
    AppConfigResponse,
    AppGridResponse,
    AppHealth,
    AppListResponse,
    AppSource,
    AppSummary,
    BlockingFindingsResponse,
    ConfigSchemaResponse,
    Execution,
    ExecutionKind,
    JobSummary,
    JobTriggerResponse,
    ListenerSummary,
    LivenessResponse,
    LogEntry,
    LogLevel,
    LogLevelRequest,
    LogLevelResponse,
    LogsByExecutionResponse,
    QuerySourceTier,
    ReadinessResponse,
    SystemStatusResponse,
    TelemetryStatusResponse,
    UnattributedBlockingResponse,
)

from hassette_client.transport import DEFAULT_REQUEST_TIMEOUT, Transport, path_segment


class HassetteClient:
    """Async client for one hassette server's HTTP API.

    The client uses the ``aiohttp.ClientSession`` it's given and never creates or closes one, so the
    caller owns the session's lifetime, connection pool and TLS settings. Inside Home Assistant, pass
    ``async_get_clientsession(hass)``.

    Every method returns a ``hassette_wire`` model, parsed leniently: unknown fields are ignored, and
    an enum or ``Literal`` value newer than this client arrives as a ``hassette_wire.UnknownValue``.
    Every network or server failure raises a :class:`~hassette_client.errors.HassetteClientError`
    subclass; the client never retries. A list response fails as a whole when any element doesn't
    match its model.

    Telemetry filters are keyword-only and named as the server names them. ``since`` is a Unix
    timestamp; records before it are left out. A filter left as ``None`` isn't sent, so the server
    applies its default.

    Args:
        session: The session to send requests on.
        base_url: The server's root URL, such as ``"http://127.0.0.1:8126"``. A path prefix is kept,
            for a server behind a reverse proxy.
        token: The web API token. With none, requests carry no ``Authorization`` header, which a server
            that trusts the caller's address as a proxy accepts.
        request_timeout: Seconds allowed for each request, including reading the body. For a slow
            app action, use a second client with a longer timeout on the same session.

    Raises:
        ValueError: A path argument is ``.`` or ``..``, or contains ``/``. Raised before any request.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        token: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.transport = Transport(session, base_url, token=token, request_timeout=request_timeout)

    async def get_health(self) -> SystemStatusResponse:
        """Get the server's status, version, connection state and boot issues.

        Pass the result to :func:`~hassette_client.check_server_version` to check the server is new
        enough for this client. This method itself works against any server version.
        """
        return await self.transport.request("GET", "/api/health", SystemStatusResponse)

    async def get_liveness(self) -> LivenessResponse:
        """Check that the server process is up and answering."""
        return await self.transport.request("GET", "/api/health/live", LivenessResponse)

    async def get_ready(self) -> ReadinessResponse:
        """Check whether the server is ready to serve.

        Returns the readiness model whether the server answers 200 (ready) or 503 (not ready); read
        its fields rather than catching an error.
        """
        return await self.transport.request("GET", "/api/health/ready", ReadinessResponse, status_model_on_503=True)

    async def get_apps(self) -> AppListResponse:
        """List every configured app with its instances and status.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        return await self.transport.request("GET", "/api/apps", AppListResponse)

    async def get_app(self, app_key: str) -> AppSummary:
        """Get one app with its instances and status.

        Raises:
            InvalidAppKeyError: ``app_key`` isn't a valid app key.
            AppNotFoundError: No app with this key is configured.
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        return await self.transport.request("GET", f"/api/apps/{path_segment(app_key)}", AppSummary)

    async def action(self, app_key: str, action: AppAction, *, instance: int | None = None) -> ActionResponse:
        """Start, stop or reload an app, or one of its instances.

        The server answers only once the action has finished, including the app's
        ``on_initialize()``, so a slow app can take longer than the client's ``request_timeout``. Use
        a second client with a longer ``request_timeout`` on the same session for those.

        After a timeout or connection error the outcome is unknown. Sending ``start`` or ``stop``
        again is safe, since each converges on a state; sending ``reload`` again reloads the app a
        second time, so check the app's status first.

        Args:
            app_key: The app to act on.
            action: ``"start"``, ``"stop"`` or ``"reload"``. Not checked locally: an action the server
                doesn't know raises the server's ``NotFoundError``.
            instance: An instance index, to act on that instance alone. ``None`` acts on every instance.

        Raises:
            InvalidAppKeyError: ``app_key`` isn't a valid app key.
            AppNotFoundError: No app with this key is configured.
            InstanceNotFoundError: ``instance`` is out of range for the app's config.
            BootstrapNotReleasedError: Apps can't be started yet; retry later. Not raised for a stop.
            AppBlockedError: The server's ``--app`` filter excludes this app. Not raised for a stop.
            ActionFailedError: The action ran but failed, or left a targeted instance failed.
            HassetteTimeoutError: No answer in time. The action may still have run, or still be running.
        """
        path = f"/api/apps/{path_segment(app_key)}"
        if instance is not None:
            path += f"/instances/{path_segment(instance)}"
        return await self.transport.request("POST", f"{path}/{path_segment(action)}", ActionResponse)

    async def get_app_config(self, app_key: str) -> AppConfigResponse:
        """Get an app's configuration, with secret fields masked.

        Raises:
            InvalidAppKeyError: ``app_key`` isn't a valid app key.
            AppNotFoundError: No app with this key is configured.
        """
        return await self.transport.request("GET", f"/api/apps/{path_segment(app_key)}/config", AppConfigResponse)

    async def get_app_source(self, app_key: str) -> AppSource:
        """Get the source code of an app's module.

        Raises:
            InvalidAppKeyError: ``app_key`` isn't a valid app key.
            AppNotFoundError: No app with this key is configured.
            SourceNotFoundError: The app's source file doesn't exist.
            PathTraversalError: The source path resolves outside the app directory.
            SourceUnavailableError: The source file exists but couldn't be read.
        """
        return await self.transport.request("GET", f"/api/apps/{path_segment(app_key)}/source", AppSource)

    async def get_recent_logs(
        self,
        *,
        limit: int | None = None,
        app_key: str | None = None,
        level: LogLevel | None = None,
        since: float | None = None,
        execution_id: str | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> list[LogEntry]:
        """Get recent log records.

        Args:
            limit: The most records to return.
            app_key: Only records emitted by this app.
            level: Only records at this level.
            since: Only records at or after this Unix timestamp.
            execution_id: Only records emitted during this handler or job execution.
            source_tier: ``"app"`` or ``"framework"`` records only, or ``"all"``.

        Raises:
            TelemetryUnavailableError: The log store couldn't be read.
        """
        params = {
            "limit": limit,
            "app_key": app_key,
            "level": level,
            "since": since,
            "execution_id": execution_id,
            "source_tier": source_tier,
        }
        return await self.transport.request("GET", "/api/logs/recent", list[LogEntry], params=params)

    async def set_log_level(self, logger: str, level: LogLevel) -> LogLevelResponse:
        """Change a logger's level on the running server."""
        body = LogLevelRequest(logger=logger, level=level)
        return await self.transport.request("PUT", "/api/logs/level", LogLevelResponse, body=body)

    async def get_execution_logs(self, execution_id: str, *, limit: int | None = None) -> LogsByExecutionResponse:
        """Get the log records one handler or job execution emitted.

        Raises:
            TelemetryUnavailableError: The log store couldn't be read.
        """
        path = f"/api/executions/{path_segment(execution_id)}"
        return await self.transport.request("GET", path, LogsByExecutionResponse, params={"limit": limit})

    async def get_listeners(
        self,
        *,
        app_key: str | None = None,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> list[ListenerSummary]:
        """List bus listeners with their invocation statistics, across apps or for one.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        params = {"app_key": app_key, "instance_index": instance_index, "since": since, "source_tier": source_tier}
        return await self.transport.request("GET", "/api/bus/listeners", list[ListenerSummary], params=params)

    async def get_config(self) -> ConfigSchemaResponse:
        """Get the server's configuration schema and values, with secret fields masked."""
        return await self.transport.request("GET", "/api/config", ConfigSchemaResponse)

    async def get_telemetry_status(self) -> TelemetryStatusResponse:
        """Check whether the telemetry store is healthy.

        Returns the status model whether the server answers 200 or 503 (degraded); read its fields
        rather than catching an error.
        """
        return await self.transport.request(
            "GET", "/api/telemetry/status", TelemetryStatusResponse, status_model_on_503=True
        )

    async def get_app_health(
        self,
        app_key: str,
        *,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> AppHealth:
        """Get an app instance's handler and job health. ``app_key="__hassette__"`` reports the framework.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/app/{path_segment(app_key)}/health"
        params = {"instance_index": instance_index, "since": since, "source_tier": source_tier}
        return await self.transport.request("GET", path, AppHealth, params=params)

    async def get_app_listeners(
        self,
        app_key: str,
        *,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> list[ListenerSummary]:
        """List an app instance's bus listeners with their invocation statistics.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/app/{path_segment(app_key)}/listeners"
        params = {"instance_index": instance_index, "since": since, "source_tier": source_tier}
        return await self.transport.request("GET", path, list[ListenerSummary], params=params)

    async def get_app_activity(
        self,
        app_key: str,
        *,
        instance_index: int | None = None,
        limit: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> list[ActivityFeedEntry]:
        """Get an app's recent handler and job executions.

        Args:
            app_key: The app.
            instance_index: One instance only. ``None`` covers every instance.
            limit: The most entries to return.
            since: Only executions at or after this Unix timestamp.
            source_tier: ``"app"`` or ``"framework"`` executions only, or ``"all"``.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/app/{path_segment(app_key)}/activity"
        params = {"instance_index": instance_index, "limit": limit, "since": since, "source_tier": source_tier}
        return await self.transport.request("GET", path, list[ActivityFeedEntry], params=params)

    async def get_app_jobs(
        self,
        app_key: str,
        *,
        instance_index: int | None = None,
        since: float | None = None,
        source_tier: QuerySourceTier | None = None,
    ) -> list[JobSummary]:
        """List an app instance's scheduled jobs with their execution statistics.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/app/{path_segment(app_key)}/jobs"
        params = {"instance_index": instance_index, "since": since, "source_tier": source_tier}
        return await self.transport.request("GET", path, list[JobSummary], params=params)

    async def get_app_blocking_findings(
        self, app_key: str, *, instance_index: int | None = None, since: float | None = None
    ) -> BlockingFindingsResponse:
        """Get the blocking-I/O findings attributed to an app's handlers and jobs.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/app/{path_segment(app_key)}/blocking"
        params = {"instance_index": instance_index, "since": since}
        return await self.transport.request("GET", path, BlockingFindingsResponse, params=params)

    async def get_blocking_findings(self, *, since: float | None = None) -> BlockingFindingsResponse:
        """Get the blocking-I/O findings across every app.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = "/api/telemetry/blocking/findings"
        return await self.transport.request("GET", path, BlockingFindingsResponse, params={"since": since})

    async def get_unattributed_blocking(self, *, since: float | None = None) -> UnattributedBlockingResponse:
        """Get event-loop stalls that couldn't be attributed to a handler or job.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = "/api/telemetry/blocking/unattributed"
        return await self.transport.request("GET", path, UnattributedBlockingResponse, params={"since": since})

    async def get_executions(
        self, *, kind: ExecutionKind | None = None, limit: int | None = None, since: float | None = None
    ) -> list[Execution]:
        """Get recent handler and job executions across every app.

        Args:
            kind: ``"handler"`` or ``"job"`` executions only. ``None`` returns both.
            limit: The most executions to return.
            since: Only executions at or after this Unix timestamp.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        params = {"kind": kind, "limit": limit, "since": since}
        return await self.transport.request("GET", "/api/telemetry/executions", list[Execution], params=params)

    async def get_listener_executions(
        self, listener_id: int, *, limit: int | None = None, since: float | None = None
    ) -> list[Execution]:
        """Get one bus listener's recent executions.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/listener/{path_segment(listener_id)}/executions"
        return await self.transport.request("GET", path, list[Execution], params={"limit": limit, "since": since})

    async def get_job_executions(
        self, job_id: int, *, limit: int | None = None, since: float | None = None
    ) -> list[Execution]:
        """Get one scheduled job's recent executions.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/job/{path_segment(job_id)}/executions"
        return await self.transport.request("GET", path, list[Execution], params={"limit": limit, "since": since})

    async def get_execution(self, execution_id: str) -> Execution | None:
        """Get one execution, or ``None`` if no execution has this ID.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        path = f"/api/telemetry/execution/{path_segment(execution_id)}"
        return await self.transport.request("GET", path, Execution | None)

    async def get_app_grid(self, *, since: float | None = None) -> AppGridResponse:
        """Get every app with its status and activity summary, as the dashboard's app grid shows them.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        return await self.transport.request("GET", "/api/telemetry/app-grid", AppGridResponse, params={"since": since})

    async def get_jobs(
        self, *, since: float | None = None, source_tier: QuerySourceTier | None = None
    ) -> list[JobSummary]:
        """List scheduled jobs across every app with their execution statistics.

        Raises:
            TelemetryUnavailableError: The telemetry store couldn't be read.
        """
        params = {"since": since, "source_tier": source_tier}
        return await self.transport.request("GET", "/api/scheduler/jobs", list[JobSummary], params=params)

    async def trigger_job(self, job_id: int) -> JobTriggerResponse:
        """Run a scheduled job now, outside its schedule.

        The server answers as soon as the run is dispatched. After a timeout or connection error the
        outcome is unknown, and sending it again may run the job twice.

        Raises:
            JobNotRegisteredError: The job has no live registration.
        """
        path = f"/api/scheduler/jobs/{path_segment(job_id)}/trigger"
        return await self.transport.request("POST", path, JobTriggerResponse)

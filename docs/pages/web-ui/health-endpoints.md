# Configure Health Checks

Hassette exposes three HTTP health endpoints and a telemetry-specific status endpoint. Each serves a different consumer.

| Signal | Endpoint | Consumer |
|---|---|---|
| Restart automation | `/api/health/live` (or non-zero exit + restart policy) | Docker healthcheck, systemd, autoheal |
| Traffic routing | `/api/health/ready` | Load balancer, reverse proxy |
| Human inspection | `/api/health` | Dashboards, `hassette status`, manual checks |
| Telemetry health | `/api/telemetry/status` | Monitoring whether the telemetry DB is functional |

## Liveness: `/api/health/live`

The liveness endpoint returns HTTP 200 with `{"status": "live"}` whenever the process is up. It performs no dependency check. Home Assistant being down, the database being unavailable, or the WebSocket being disconnected have no effect on the response.

| Condition | HTTP | Body |
|---|---|---|
| Process is up, event loop responding | 200 | `{"status": "live"}` |
| Event loop wedged / process crashed | — | connection refused or probe timeout |

Container healthchecks and autoheal tools belong at this endpoint. An HA outage keeps the probe green. Only a true process failure makes it fail.

### Docker Compose example

```yaml
--8<-- "pages/web-ui/snippets/healthcheck-live.yml"
```

Docker restarts Hassette only when the process crashes (non-zero exit). HA outages do not trigger a restart.

## Readiness: `/api/health/ready`

The readiness endpoint returns HTTP 200 when the WebSocket connection is active (`ok`). It returns HTTP 503 when the status is `degraded` or `starting`.

| `status` | HTTP | `ready` |
|---|---|---|
| `ok` | 200 | `true` |
| `degraded` | 503 | `false` |
| `starting` | 503 | `false` |

Response body: `{"status": "<status>", "ready": <bool>}`.

This endpoint serves load-balancer traffic routing — holding traffic until the WebSocket connection is live. It is not suitable for restart automation. It returns 503 during any HA outage, which triggers a restart loop.

## Aggregate status: `/api/health`

The full status endpoint returns HTTP 200 in all states while the process can serve. The response body is the complete `SystemStatusResponse`: uptime, entity count, app count, running services, version, and boot issues. Per-service detail is in the `services` field of the response.

| `status` body field | HTTP | Meaning |
|---|---|---|
| `ok` | 200 | WebSocket connected |
| `degraded` | 200 | Was connected; currently disconnected |
| `starting` | 200 | Initial connection not yet complete |

The handler never returns 503. This endpoint is not suitable as a restart or routing signal.

## Fatal exit

A fatal failure causes Hassette to exit with code `1`. Fatal failures include a PERMANENT service exhausting its restart budget, a fatal error, or a startup failure. Hassette records a `failure` status to the telemetry session before exiting.

A clean operator shutdown (SIGTERM / `docker stop`) exits with code `0`.

- `systemd` with `Restart=on-failure` restarts after a crash but not after a clean stop.
- Docker with `restart: unless-stopped` restarts after a crash but not after `docker stop`.
- An HA outage does not trigger a restart. Hassette stays up, `/api/health/live` stays 200.

## Related pages

- [Docker Troubleshooting](../getting-started/docker/troubleshooting.md) — restart loops caused by pointing healthchecks at `/api/health/ready`
- [Database & Telemetry](../core-concepts/database-telemetry.md) — telemetry health and `/api/telemetry/status`
- [Web UI Overview](index.md) — the browser-based monitoring dashboard

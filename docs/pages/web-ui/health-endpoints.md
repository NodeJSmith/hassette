# Health Endpoints

Hassette exposes three HTTP endpoints for health signaling. Each serves a different consumer: restart automation, traffic routing, and human inspection.

## `/api/health/live`

The liveness endpoint returns HTTP 200 with `{"status": "live"}` whenever the Hassette process is up and the event loop can respond. It performs no dependency check — Home Assistant being down, the telemetry database being unavailable, or the WebSocket being disconnected never changes its response.

| Condition | HTTP | Body |
|---|---|---|
| Process is up, event loop responding | 200 | `{"status": "live"}` |
| Event loop wedged / process crashed | — | connection refused or probe timeout |

**Use this endpoint for container restart automation** — Docker healthchecks and autoheal tools. An HA outage keeps the probe green; only a true Hassette process failure makes it fail.

## `/api/health/ready`

The readiness endpoint returns HTTP 200 when the system status is `ok` (WebSocket currently connected). It returns HTTP 503 when the status is `degraded` or `starting`.

| `status` | HTTP | `ready` |
|---|---|---|
| `ok` | 200 | `true` |
| `degraded` | 503 | `false` |
| `starting` | 503 | `false` |

Response body shape: `{"status": "<status>", "ready": <bool>}`.

**Use this endpoint for load-balancer traffic routing** — to hold traffic until Hassette has an active WebSocket connection. Do not use it for restart automation: it returns 503 during any HA outage, which would cause a restart loop whenever Home Assistant restarts.

## `/api/health`

The full status endpoint returns HTTP 200 in all states while the process can serve. The response body is the complete `SystemStatusResponse`, including uptime, entity count, app count, running services, version, and boot issues.

| `status` body field | HTTP | Meaning |
|---|---|---|
| `ok` | 200 | WebSocket connected; all services running |
| `degraded` | 200 | Was connected at least once; currently disconnected |
| `starting` | 200 | Has not finished the initial connection yet |

**Use this endpoint for the human-readable aggregate view** — dashboards, `hassette status`, and manual inspection. It never returns 503 from the handler, so it is not suitable as a restart or routing signal.

## Fatal Exit

A fatal failure — a PERMANENT service exhausting its restart budget, a fatal error, or a startup failure — causes Hassette to exit with a non-zero exit code (`1`). Before exiting, Hassette records a `failure` status to the current telemetry session.

A clean operator shutdown (SIGTERM / `docker stop`) exits with code `0`.

This means:

- `systemd` with `Restart=on-failure` restarts Hassette after a crash but not after a clean stop.
- Docker with `restart: unless-stopped` restarts after a crash but not after an explicit `docker stop`.
- An HA outage does not trigger a restart — Hassette stays up, `/api/health/live` stays 200.

## Summary

| Signal | Endpoint | When to use |
|---|---|---|
| Restart automation | `/api/health/live` (or non-zero exit + restart policy) | Container healthcheck, systemd, autoheal |
| Traffic routing | `/api/health/ready` | Load balancer, reverse proxy routing rules |
| Human inspection | `/api/health` | Dashboards, `hassette status`, manual checks |
| Telemetry health | `/api/telemetry/status` | Monitor whether the telemetry DB is functional |

## Docker Compose Example

```yaml
--8<-- "pages/web-ui/snippets/healthcheck-live.yml"
```

With this configuration, Docker restarts Hassette only when the process crashes (non-zero exit). HA outages do not trigger a restart.

## Related Pages

- [Docker Troubleshooting](../getting-started/docker/troubleshooting.md) — common Docker issues including restart loops
- [Database & Telemetry](../core-concepts/database-telemetry.md) — telemetry health and the `/api/telemetry/status` endpoint
- [Web UI Overview](index.md) — the browser-based monitoring interface

# Docker Troubleshooting

Each section below covers one symptom. Jump to the one that matches your situation.

## Container Exits Immediately

The container starts and stops within a few seconds. Check the logs first:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs.sh"
```

The two most common causes are a missing token and an unreachable Home Assistant instance.

**Missing token.** Hassette reads `HASSETTE__TOKEN` from `/config/.env` inside the container. If that value is absent, Hassette exits at startup. Open your `config/.env` file and confirm the line is present:

```
HASSETTE__TOKEN=your_long_lived_token_here
```

**Wrong base URL.** `HASSETTE__BASE_URL` must point to Home Assistant's HTTP interface. Use `http://homeassistant:8123` when running on the same Docker network, or your HA instance's IP address otherwise. A trailing slash or `https://` when HA serves plain HTTP will cause a connection failure.

**Network not reachable.** If the URL looks correct, test the connection from inside the container:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-curl-ha.sh"
```

A healthy response returns a JSON object with a `message` key. An empty response or connection error means the container can't reach HA on that address.

## "Connected" But Apps Don't Load

Hassette reports a successful connection in the logs, but your apps never initialize.

**Apps directory not mounted.** Hassette looks for apps at `/apps` inside the container. Verify the mount is working:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-ls-apps.sh"
```

If this returns an empty directory or an error, check your `volumes:` block in `compose.yml`. It should include a line like `./apps:/apps`.

**Syntax error in an app file.** A Python syntax error prevents that app from loading. Scan the logs for errors:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-grep-errors.sh"
```

Look for a `SyntaxError` or `ImportError` with a file path. Fix the error in that file, then restart with `docker compose restart hassette`.

## Dependencies Won't Install

Your app imports a third-party package, but Hassette reports an `ImportError` at startup.

Hassette only installs from `requirements.txt` when `HASSETTE__INSTALL_DEPS=1` is set in the compose `environment:` block. Check your `compose.yml`:

```yaml
environment:
  HASSETTE__INSTALL_DEPS: "1"
```

If the variable is set, confirm `requirements.txt` is mounted and readable at `/config/requirements.txt` inside the container:

```bash
docker compose exec hassette ls /config/requirements.txt
```

Then check whether the install ran at startup:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-dep-install-logs.sh"
```

If you see no install output, `HASSETTE__INSTALL_DEPS` was not picked up. Run `docker compose down && docker compose up -d` to reload the environment.

## Can't Access the Web UI

You navigate to `http://your-host:8126` and get a connection refused error.

The port is not published unless your `compose.yml` includes a `ports:` mapping for the Hassette service:

```yaml
services:
  hassette:
    ports:
      - "8126:8126"
```

If the port is listed but you still get connection refused, check the bind address. `"127.0.0.1:8126:8126"` only accepts connections from localhost. Use `"8126:8126"` to accept connections from any interface.

After updating `compose.yml`, run `docker compose up -d` to apply the change.

## Changes to Apps Don't Take Effect

You edit an app file on disk, but Hassette continues running the old version.

The file watcher is off in production mode by default. Restart the container to pick up your changes:

```bash
docker compose restart hassette
```

To apply edits without restarting, set `watch_files = true` and `allow_reload_in_prod = true` in your `hassette.toml`.

## Hassette Restarts Whenever Home Assistant Goes Down

**Symptom:** Hassette keeps restarting in a loop whenever Home Assistant restarts or goes offline, even though Hassette itself is healthy.

**Cause:** A Docker healthcheck or an autoheal tool (e.g. `willfarrell/autoheal`) is pointed at `/api/health/ready`. That endpoint returns HTTP 503 when Hassette cannot reach Home Assistant, which looks unhealthy to Docker and triggers a restart. The container is marked unhealthy during every HA outage, including routine HA restarts, so autoheal keeps killing and restarting Hassette unnecessarily.

**Fix:** Point your healthcheck at `/api/health/live` instead. The liveness endpoint returns 200 whenever the Hassette event loop can respond, regardless of Home Assistant connectivity. Only a true process failure (wedged event loop, container crash, non-zero exit) makes a liveness probe fail.

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-healthcheck-live.yml"
```

If you need a separate traffic-routing signal, use `/api/health/ready`, but keep it out of any healthcheck that triggers restarts. See [Configure Health Checks](../../web-ui/health-endpoints.md) for the full reference.

## Getting Help

If none of the above resolved your issue:

- Search [GitHub Issues](https://github.com/NodeJSmith/hassette/issues) for your error message. Someone may have hit the same thing.
- Open a new issue with your `docker compose logs hassette` output and your `compose.yml` (redact your token).

For problems not specific to Docker (app logic, bus subscriptions, scheduler behavior), see the main [Troubleshooting](../../troubleshooting.md) page.

# Watchdog, Backups & Troubleshooting

Keep the add-on running, know what a backup holds, and fix the add-on when it stops or misbehaves. For installing the add-on, see [Add-on Setup](index.md). For options and the config folder, see [Add-on Configuration](configuration.md).

## Watchdog

Watchdog is a Home Assistant add-on setting. Supervisor, the part of Home Assistant that runs add-ons, uses it to restart a failed add-on. Turn it on in the add-on's **Info** tab when you install it. Without it, a stopped add-on stays stopped until you start it from its page. Watchdog restarts Hassette in three cases:

- Hassette crashes.
- Hassette exits on a fatal error.
- The health check fails three times in a row.

The health check requests `/api/health/live` every 30 seconds and allows 5 seconds for a reply. Three failed checks mark the container unhealthy, and Supervisor restarts it.

For the first 35 minutes after a start, failed checks don't count, so a slow dependency install isn't treated as a hang. The first passing check ends this grace period early. A start that never finishes is caught when the 35 minutes end, so check the **Log** tab sooner if the sidebar stays blank.

Restarts back off, starting at 10 seconds and doubling. After 10 attempts in 30 minutes, Supervisor stops trying. The add-on stays stopped, and the log shows why it kept failing.

Watchdog never restarts Hassette because Home Assistant is down. The liveness check stays green through a Home Assistant outage, and Hassette waits and reconnects on its own. See [Health Endpoints](../../web-ui/health-endpoints.md) and [Health and supervisors](../../operating/index.md#health-and-supervisors).

## Startup

Dependencies install on every start, not only the first. The add-on installs the `uv.lock` project if there is one, then the `python_packages` option. See [Dependencies](configuration.md#dependencies). A package cache in the add-on's `/data` folder makes later starts quick.

### When the network is down

If the package index can't be reached, the add-on installs from the cache instead. This happens when Home Assistant boots before your router, for example:

```text
WARNING: couldn't reach the package index (exit <code>); retrying from the uv cache (--offline)
...
Installed from the uv cache.
```

The `...` stands for uv's own output, and the exit code varies. If the cache can't supply a package, Hassette starts anyway. The log names each install that didn't run:

```text
WARNING: the offline install failed too (exit <code>); continuing without the python_packages option
...
─────────────────────────────────────────────────────────
  HASSETTE IS STARTING WITHOUT SOME DEPENDENCIES

  The package index couldn't be reached and the uv cache
  doesn't hold everything needed, so these installs didn't run:
    - the python_packages option

  Apps that import a missing package will fail to load.
  Once the network is back, restart the add-on from its page.
─────────────────────────────────────────────────────────
```

Each label under the banner is a skipped step. A skipped project install shows as `your project (<folder>/uv.lock)`.

### When the add-on can't start

A config error or a dependency conflict stops the add-on at once. The log ends with a banner that names what failed and how to fix it:

```text
─────────────────────────────────────────────────────────
  HASSETTE CAN'T START: the configuration is invalid (see above)

  Fix the setting named above, then restart the add-on from its page
─────────────────────────────────────────────────────────
```

The lines above the banner name the setting. With Watchdog off, the add-on stays stopped. With Watchdog on, Supervisor restarts it with backoff. Each restart halts again until the setting is fixed or Supervisor gives up.

### Stopping

The add-on has 60 seconds to stop. That covers Hassette's 45-second shutdown plus 15 seconds for the final database snapshot, which is slow on an SD card. Raising `lifecycle.total_shutdown_timeout_seconds` past 45 seconds risks Supervisor stopping Hassette before the snapshot is written. See [Backups](#backups).

## Backups

Hassette keeps its telemetry history in a database. A plain file copy of it can catch a write halfway, so the add-on makes a safe copy, a snapshot, first.

Backups run while Hassette keeps running. Before each backup, the add-on writes a consistent snapshot of the database. The backup stores that snapshot in place of the live database files (`hassette.db`, `hassette.db-wal` and `hassette.db-shm`). Restoring the backup brings telemetry history back to the moment of the snapshot.

After a restore, the database file is missing and the snapshot is present. The add-on copies the snapshot into place at start and logs:

```text
Restored the database from the backup snapshot /data/backup/hassette-snapshot.db
```

Every other start logs `No database restore needed (the database exists, or there is no snapshot)`.

Each clean stop also writes the snapshot. Supervisor runs no pre-backup step for a stopped add-on, so its backup holds the copy from the last clean stop. That copy is older if Hassette crashed or was killed instead of stopping cleanly. It is also older if writing the snapshot at stop failed. That failure leaves an error in the log containing `Couldn't write the shutdown snapshot to`. The add-on sets the snapshot path itself; see [Settings the Add-on Owns](configuration.md#settings-the-add-on-owns).

The backup includes the config folder: your apps, `hassette.toml` and the web API token. It leaves out the package cache, which refills on the next start.

### When the snapshot fails

If the snapshot before a backup fails, the add-on is left out of that backup, `/config` included. The backup does not carry an older database in its place. The backup's details list Hassette as failed, and the add-on's log gives the reason:

```text
ERROR: the backup can't include hassette's database: couldn't snapshot /data/hassette.db to /data/backup/hassette-snapshot.db: <error>
```

The text after `hassette-snapshot.db:` is the underlying error. Other add-ons and Home Assistant itself still back up. See [A backup lists Hassette as failed](#a-backup-lists-hassette-as-failed).

## Troubleshooting

Each section covers one symptom: what you see, why, and what to do. Start with the add-on's **Log** tab.

### The add-on stops with a "HASSETTE CAN'T START" banner

The add-on hit an error it can't fix by retrying. The text after `HASSETTE CAN'T START:` says which:

| Banner text | Cause | Fix |
|---|---|---|
| `the configuration is invalid (see above)` | A setting in `hassette.toml` or `.env` is wrong or unknown. | Fix the setting named above the banner. |
| `a dependency conflict (see above)` | A package in your `uv.lock` project or `python_packages` conflicts with this version of Hassette. | Relax or remove the pin named above. For a `uv.lock` project, run `uv lock` on your own computer and copy the new `uv.lock` into the config folder. |
| `couldn't restore the database from the backup's snapshot` | Copying the snapshot into place failed. The line above the banner gives the reason. | Restart the add-on. If it halts again, report it. |
| `couldn't write the starter files to /config` | Seeding the empty config folder failed. | Restart the add-on. If it halts again, report it. |
| `couldn't read the add-on options (/data/options.json)` | The saved options file is damaged. | Save the **Configuration** tab again, then restart. |
| `the Docker image is corrupt` | Hassette failed to import inside the image. | Update or reinstall the add-on. |
| `the image's constraints file is incomplete` | The image is missing its version pins. | Update or reinstall the add-on. |
| `'hassette run --check' failed unexpectedly (see above)` | The config check crashed. | Read the error above the banner, then report it. |

After a fix, restart the add-on from its page. To report a halt, see [Report problems](#report-problems). A box above a dependency-conflict banner gives hints for the failed install. It reads `DEPENDENCY CONFLICT`, or `EXPORT FAILED` when the `uv.lock` export failed. Its "commit uv.lock" advice means copying the new `uv.lock` into the add-on's config folder.

A banner reading `this image only works as a Home Assistant add-on` has its [own entry below](#the-image-logs-this-image-only-works-as-a-home-assistant-add-on).

### Hassette starts but an app fails to import a package

The log shows a `HASSETTE IS STARTING WITHOUT SOME DEPENDENCIES` banner. An app then logs `ImportError` or `ModuleNotFoundError`. The package index was unreachable and the cache didn't hold the package, so the install was skipped. Apps that don't need the package still run.

Once the network is back, restart the add-on from its page. The install runs again and fills the cache.

If the log has no banner, look for the line `project install: skipped`. A `pyproject.toml` without a `uv.lock` isn't installed, so run `uv lock` and copy both files. Otherwise the package was never listed. Add it to `python_packages` or your `uv.lock` project. See [Dependencies](configuration.md#dependencies).

### The Discovered card never appears

The card needs three things: the Hassette integration installed through HACS, Hassette serving, and a successful announce. Check the log for one of these lines:

```text
Announced hassette to Home Assistant; the hassette integration can now be set up from its Discovered card
```

```text
WARNING: couldn't announce hassette to Home Assistant through Supervisor discovery: <reason>
```

```text
WARNING: couldn't announce hassette to Home Assistant (reading /config/.web_api_token failed): <reason>
```

- **No announce line at all.** The add-on announces only after Hassette serves. If Hassette is still installing dependencies or stuck, the announce waits. Fix the start first.
- **A WARNING line.** The reason follows the colon. The add-on keeps running. Restart it to announce again, since every start announces.
- **The announce line is there, but no card.** Install the integration through HACS and restart Home Assistant. See [Home Assistant Integration](../home-assistant-integration.md). Then check **Settings → Devices & services**.

### The integration stops working after rotating the token

An integration paired through the Discovered card fixes itself. The next time a request fails, it reads the new token from the add-on. An integration you added by hand doesn't. Open it in **Settings → Devices & services**, choose **Reconfigure**, and paste the new token. See [Web API Token](configuration.md#web-api-token) for where to find it.

### The add-on stays stopped

Open the **Log** tab and read the last lines. A banner or an error line says why it stopped.

- **Watchdog is off.** The add-on stays stopped after any exit. Fix the cause shown in the log, turn on Watchdog on the **Info** tab, and choose **Start**.
- **Watchdog gave up.** Ten restarts in 30 minutes means something fails on every start. The log holds the repeated cause. Fix it, then choose **Start**.

### A backup lists Hassette as failed

The snapshot before the backup failed, so the add-on and its `/config` folder are not in that backup. Find the `ERROR: the backup can't include hassette's database:` line in the add-on's log. The text after it gives the reason, such as a full disk or an unreadable database file. Fix it and run the backup again.

### The image logs "this image only works as a Home Assistant add-on"

This applies only if you ran the add-on image yourself, with Docker, outside Home Assistant. `SUPERVISOR_TOKEN` is not set there:

```text
─────────────────────────────────────────────────────────
  HASSETTE CAN'T START: this image only works as a Home Assistant add-on (SUPERVISOR_TOKEN is not set)

  To run hassette in plain Docker, use the ghcr.io/nodejsmith/hassette image instead
─────────────────────────────────────────────────────────
```

Use the `ghcr.io/nodejsmith/hassette` image with [Docker Setup](../docker/index.md) instead.

## Report problems

Report problems at <https://github.com/NodeJSmith/hassette/issues>. Include the add-on's log.

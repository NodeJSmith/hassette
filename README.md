<p align="center">
  <img src="https://raw.githubusercontent.com/NodeJSmith/hassette/main/docs/_static/hassette-logo.svg" />
</p>

# Hassette

[![PyPI version](https://badge.fury.io/py/hassette.svg)](https://badge.fury.io/py/hassette)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/license/MIT)
[![Documentation Status](https://app.readthedocs.org/projects/hassette/badge/?version=stable)](https://hassette.readthedocs.io/en/stable/?badge=stable)
[![codecov](https://codecov.io/github/NodeJSmith/hassette/graph/badge.svg?token=I3E5S2E3X8)](https://codecov.io/github/NodeJSmith/hassette)

Hassette is a Python framework for writing Home Assistant automations as typed, testable code. It connects to Home Assistant, runs your apps, and shows you what each one is doing.

**Documentation:** https://hassette.readthedocs.io

In `apps/motion_lights.py`:

```python
from hassette import App, AppConfig


class MotionLightsConfig(AppConfig):
    motion_sensor: str = "binary_sensor.hallway_motion"
    light: str = "light.hallway"


class MotionLights(App[MotionLightsConfig]):
    async def on_initialize(self):
        cfg = self.app_config
        await self.bus.on_state_change(cfg.motion_sensor, changed_to="on", handler=self.lights_on, name="motion_on")
        await self.bus.on_state_change(
            cfg.motion_sensor, changed_to="off", duration=120, handler=self.lights_off, name="motion_off"
        )

    async def lights_on(self):
        await self.api.turn_on(self.app_config.light, brightness=200)

    async def lights_off(self):
        await self.api.turn_off(self.app_config.light)
```

The light turns on when motion starts. It turns off once the sensor has stayed clear for 120 seconds: `duration` fires the handler only if the new state holds that long, so motion coming back cancels the turn-off.

- `on_initialize` runs once when the app starts. `self.bus` subscribes handlers to things that happen in Home Assistant, `self.api` calls services, and `name` labels each subscription in the web UI and CLI.
- App methods are `async def`, and calls to `self.bus`, `self.api` and `self.scheduler` take `await`. That's all the async you need to get started. Not ready for async? [`AppSync`](https://hassette.readthedocs.io/en/stable/pages/core-concepts/apps/#synchronous-apps) runs plain synchronous code, with `.sync` versions of the bus, scheduler and API.
- Handlers receive only the parameters they declare. These two need nothing, so they take nothing.

`MotionLightsConfig` holds the app's settings as typed fields. Override them in `hassette.toml`, once per room if you like:

```toml
# "motion_lights" is the app key: your name for it in the CLI and UI
[hassette.apps.motion_lights]
filename = "motion_lights.py"
class_name = "MotionLights"

# Each [[...config]] block runs one instance of the app
[[hassette.apps.motion_lights.config]]
instance_name = "hallway"  # uses the defaults from MotionLightsConfig

[[hassette.apps.motion_lights.config]]
instance_name = "garage"
motion_sensor = "binary_sensor.garage_motion"
light = "light.garage"
```

## Features

- **Typed state.** Every entity domain has a generated model, so `self.states.light` hands you lights whose `brightness` and `color_temp_kelvin` autocomplete in your editor instead of being dictionary lookups. Reads come from a local cache, not a round trip to Home Assistant.
- **Filtering built into subscriptions.** Glob patterns (`sensor.*_temperature`), value conditions (`C.Increased()`), debounce and throttle (at most one call per N seconds) are arguments to `on_state_change` and friends, so handlers don't start with a block of `if` checks.
- **Handlers declare their inputs.** Ask for the new state, the old one, or the entity ID in the handler's signature and Hassette passes it in, in the style of FastAPI's dependencies. See [Dependency Injection](https://hassette.readthedocs.io/en/stable/pages/core-concepts/bus/dependency-injection/).
- **Scheduler.** Run a function after a delay, every N minutes, daily at a set time, or on a cron schedule. A job set for 07:00 still runs at 07:00 after the clocks change.
- **Test harness.** `AppTestHarness` runs an app without a live Home Assistant: seed states, simulate events, move time forward, and assert which services it called. See [Write Your First Test](https://hassette.readthedocs.io/en/stable/pages/testing/).
- **Web UI and CLI.** Each app's health, handler and job history, logs and config, in the browser or the terminal.
- **Control apps from Home Assistant.** An optional HACS integration turns each app into a Home Assistant device you can start, stop and reload.
- **Built to keep running.** Hassette reconnects to Home Assistant on its own, reloads apps when you edit them in dev mode, and flags synchronous code that would freeze every other app, naming the app responsible.

## Get Started

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv tool install hassette
hassette run
```

`uv tool install` puts the `hassette` command on your path. `hassette run` loads the apps in your project's `apps/` directory and connects to Home Assistant, using a URL and access token you set in a `.env` file. Once it's up, `hassette status` reports the connection and `hassette app` lists your apps.

The [Quickstart](https://hassette.readthedocs.io/en/stable/pages/getting-started/) takes you from an empty directory to a running app, including creating the Home Assistant token. To run Hassette in a container, see [Docker Setup](https://hassette.readthedocs.io/en/stable/pages/getting-started/docker/). Not sure Hassette fits? Read [Is Hassette Right for You?](https://hassette.readthedocs.io/en/stable/pages/getting-started/is-hassette-right-for-you/)

### Coming from AppDaemon?

Most of what you know carries over: `listen_state` becomes `self.bus.on_state_change`, `call_service` becomes `self.api.call_service`, `run_in` and `run_daily` keep their names on `self.scheduler`, and `self.args` becomes a typed `AppConfig`. Hassette and AppDaemon can run against the same Home Assistant at once, so you can port one app at a time. The [migration guide](https://hassette.readthedocs.io/en/stable/pages/migration/) walks through each piece, including async basics and a checklist for porting an app.

## Web UI

The web UI runs by default at `http://<host>:8126/` (`http://localhost:8126/` on the machine running Hassette). It shows each app's status and health, the history of every handler and scheduled job down to single executions, live logs, and the resolved configuration. You can start, stop and reload apps and trigger jobs from it. It's protected by a token Hassette generates on first start; the [Web UI docs](https://hassette.readthedocs.io/en/stable/pages/web-ui/) show where to find it.

<p align="center">
  <img src="https://raw.githubusercontent.com/NodeJSmith/hassette/main/docs/_static/web_ui_apps.png" alt="Hassette Web UI — Apps page" />
</p>

## CLI

The same information is available from the terminal. `--app` takes the app's key from `hassette.toml`, and a listener is one bus subscription:

```bash
hassette status                                   # connection and system health
hassette app                                      # every app and its status
hassette listener --app motion_lights --since 1h  # subscription activity for one app
hassette log --app motion_lights --since 1h       # recent logs for one app
hassette listener --app motion_lights --json | jq '.[] | select(.failed > 0)'
```

See the [CLI docs](https://hassette.readthedocs.io/en/stable/pages/cli/).

## Home Assistant Integration

The optional [Hassette integration](https://github.com/NodeJSmith/hass-hassette), installed through HACS (the Home Assistant Community Store), creates a Home Assistant device for each app with:

- a **switch** that starts and stops the app
- a **reload button** that re-imports the app's code and restarts it
- a **status sensor**

Use them on dashboards or in Home Assistant automations, for example to stop an app while you're away. It needs Hassette 0.56.0 or newer and Home Assistant 2026.9 or newer. Setup takes a few minutes: [Control Apps from Home Assistant](https://hassette.readthedocs.io/en/stable/pages/getting-started/home-assistant-integration/).

## Examples

[`examples/`](https://github.com/NodeJSmith/hassette/tree/main/examples) has complete apps, and the docs have [recipes](https://hassette.readthedocs.io/en/stable/pages/recipes/) for common automations:

- [motion_lights.py](https://github.com/NodeJSmith/hassette/blob/main/examples/motion_lights.py): motion-activated lights, one class configured for several rooms
- [climate_controller.py](https://github.com/NodeJSmith/hassette/blob/main/examples/climate_controller.py): temperature monitoring across sensors with glob patterns
- [cover_scheduler.py](https://github.com/NodeJSmith/hassette/blob/main/examples/cover_scheduler.py): daily and cron schedules for blinds
- [presence_tracker.py](https://github.com/NodeJSmith/hassette/blob/main/examples/presence_tracker.py): adding and removing subscriptions at runtime
- [security_monitor.py](https://github.com/NodeJSmith/hassette/blob/main/examples/security_monitor.py): reacting to service calls, with synchronous handlers and throttling

## Project Status

Hassette is pre-1.0 and under active development. Minor releases can include breaking changes, each listed in the [changelog](CHANGELOG.md) with migration steps in the [upgrading guide](https://hassette.readthedocs.io/en/stable/pages/operating/upgrading/). Pin the minor version you're on (for example `hassette~=0.57.0`) and read the changelog before upgrading.

## Contributing

Bug reports, feature ideas, docs fixes and code are all welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=NodeJSmith/hassette&type=date&legend=top-left)](https://www.star-history.com/#NodeJSmith/hassette&type=date&legend=top-left)

## License

[MIT](LICENSE)

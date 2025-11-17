# Getting Started

This guide walks through setting up Hassette with a simple app in a local development environment.

!!! tip "Running in Docker?"
    For production deployments or if you prefer Docker, see the [Docker Deployment](docker.md) guide instead. This page covers local development with `uv`.

## Prerequisites

- A running Home Assistant instance with WebSocket API access.
- A long-lived access token from your Home Assistant profile.
- [`uv`](https://docs.astral.sh/uv/) installed.

## Overview

Hassette only needs a Home Assistant URL and access token. You’ll probably want an app as well—it won’t do much without one.

!!! tip "Should I create a package?"
    If you plan to import apps from multiple files or use `isinstance` checks, create a proper Python package with `__init__.py` files. This guide shows the package approach, but a simple directory of `.py` files works fine if you only need lightweight scripts.

### 1. Create a directory and package for your apps

`uv` is used throughout the examples, but feel free to adapt the structure to your tooling.

```bash
mkdir hassette_apps
cd hassette_apps

uv init --lib          # creates a package with __init__.py + pyproject.toml
uv add hassette
```

### 2. Test connectivity

Before writing an app, confirm Hassette can connect to Home Assistant.

```bash
uv run hassette --base-url 'http://localhost:8123' \
  -t 'YOUR_LONG_LIVED_ACCESS_TOKEN' \
  --app-dir .
```

You should see logs showing a successful connection.

![Hassette logs showing successful connection to Home Assistant](../../_static/getting-started-logs.png)

!!! note "Security tip"
    Never commit your access token to version control. In the next section we’ll use configuration files and environment variables to keep secrets out of source control.

### 3. Create your first app

An app is a Python class inheriting from `App`. Apps are generic on a configuration type, so you get typed configuration through an `AppConfig` subclass passed as the generic parameter.

!!! note
    Apps share the `Resource` lifecycle. The primary hook is `on_initialize`, which runs when the app starts (including hot reloads). Use it to set up event listeners, schedule tasks, and perform other startup logic. `on_shutdown` is available for cleanup, but all subscriptions and scheduled jobs are tracked by the app’s `TaskBucket` and cleaned up automatically.

Create `src/hassette_apps/hello_world.py`:

```bash
touch src/hassette_apps/hello_world.py
```

Add the following:

```python
from typing import Annotated

from hassette import App, AppConfig, states
from hassette import dependencies as D


class HelloWorldConfig(AppConfig):
    greeting: str = "Hello, World!"
    motion_sensor: str = "binary_sensor.motion"


class HelloWorld(App[HelloWorldConfig]):
    async def on_initialize(self) -> None:
        self.logger.info(self.app_config.greeting)

        # Listen for motion using dependency injection
        self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion,
            changed_to="on",
        )

    async def on_motion(
        self,
        new_state: Annotated[states.BinarySensorState, D.StateNew],
        entity_id: Annotated[str, D.EntityId],
    ) -> None:
        """Handler demonstrating dependency injection.

        Instead of manually accessing event.payload.data, we use Annotated
        type hints to automatically extract the new state and entity ID.
        """
        friendly_name = new_state.attributes.friendly_name or entity_id
        self.logger.info("Motion detected on %s!", friendly_name)
```

`HelloWorldConfig` defines configuration fields with defaults. The app inherits from `App` with the config type specified.

In `on_initialize`, we log the greeting and set up an event handler using `self.bus.on_state_change`.

The `on_motion` handler demonstrates **dependency injection** — instead of receiving the full event object and manually accessing its properties, we use `Annotated` type hints with markers from `hassette.dependencies` to automatically extract just the data we need. This results in cleaner, more readable code.

You don't need additional wiring—Hassette automatically discovers apps in the configured directory (controlled by `HassetteConfig.autodetect_apps`).

### 4. Run Hassette

Run Hassette again to see the app in action:

```bash
uv run hassette --base-url 'http://localhost:8123' -t 'YOUR_LONG_LIVED_ACCESS_TOKEN' --app-dir .
```

You should see logs showing the app starting and the greeting being logged.

![Hassette logs showing Hello World message](../../_static/getting-started-app-logs.png)

## Configuration: make things easier on yourself

So far we’ve taken the long path to show the mechanics. In practice you’ll want a configuration file.

Configuration files are TOML and define both global Hassette settings and app-specific settings. Hassette looks for `hassette.toml` in:

1. `/config/hassette.toml`
2. `./hassette.toml`
3. `./config/hassette.toml`

`.env` files are searched in the same locations. Override either path with `--config-file / -c` or `--env-file / -e`.

```bash
uv run hassette -c ./config/hassette.toml -e ./config/.env
```

### Home Assistant token

Generate a long-lived access token from your Home Assistant user profile. Provide it through one of:

- Environment variables: `HASSETTE__TOKEN`, `HOME_ASSISTANT_TOKEN`, or `HA_TOKEN`.
- CLI arguments: `--token` / `-t`.

### `hassette.toml`

Use the config file to set Hassette defaults and register apps:

```toml
[hassette]
base_url = "http://localhost:8123"
app_dir = "src/hassette_apps"

[apps.hello_world]
filename = "hello_world.py"
class_name = "HelloWorld"
enabled = true

[[apps.hello_world.config]]
greeting = "Hello from Hassette!"
```

Run Hassette with no CLI flags and it will pick up this configuration (or provide `-c` if the file lives elsewhere):

```bash
uv run hassette
# or
uv run hassette -c ./path/to/hassette.toml
```

You should now see the greeting defined in TOML.

![Hassette logs showing greeting from config file](../../_static/getting-started-config-logs.png)

## What’s next?

Now that Hassette is running with your first app, here are logical next steps.

### 🏗️ Build real automations

- [Event handling patterns](../core-concepts/bus/index.md) – react to state changes, service calls, and custom events.
- [Scheduling tasks](../core-concepts/scheduler/index.md) – run code on intervals, cron schedules, or delays.
- [API usage](../core-concepts/api/index.md) – call services, query states, and interact with Home Assistant.

### ⚙️ Configure your setup

- [Configuration options](../core-concepts/configuration/index.md) – environment variables, secrets, and TOML settings.
- [App patterns](../core-concepts/apps/index.md) – multi-instance apps, typed configs, lifecycle hooks.

### 📚 Learn more

- [Why Hassette?](../why-hassette.md) – the story and philosophy behind the framework.
- [vs AppDaemon](../appdaemon-comparison.md) – migration notes if you’re switching from AppDaemon.

### 🔧 Development workflow

- File watching and hot reloading already work out of the box.
- Testing and debugging guides are coming soon.

### Need help?

- [GitHub Issues](https://github.com/NodeJSmith/hassette/issues) for bugs and feature requests.
- [GitHub Discussions](https://github.com/NodeJSmith/hassette/discussions) for questions and community support.

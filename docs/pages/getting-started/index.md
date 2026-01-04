# Getting Started

This guide walks through setting up Hassette with a simple app in a local development environment.

!!! tip "Running in Docker?"
    For production deployments or if you prefer Docker, see the [Docker Deployment](docker/index.md) guide instead. This page covers local development with `uv`.

## Prerequisites

- A running Home Assistant instance with WebSocket API access.
- A long-lived access token from your Home Assistant profile.
- `pip` or `uv` installed for running Hassette.

## Overview

Hassette only needs a Home Assistant URL and access token. You’ll probably want an app as well—Hassette won’t do much without one.

!!! tip "Should I create a package?"
    If you plan to import apps from multiple files or use `isinstance` checks, create a proper Python package that can be installed. This guide uses a simple structure for clarity.

### 1. Create a directory and install Hassette

```bash
mkdir apps
cd apps

pip install hassette
```

!!! note
    If you are using `uv`, you would instead run `uv pip install hassette`.

### 2. Test connectivity

Before writing an app, confirm Hassette can connect to Home Assistant. You'll need your Home Assistant URL and long-lived access token.

If you don't have a token yet, you can follow the steps in the [Creating a Home Assistant token](ha_token.md) guide.

```bash
python -m hassette --base-url 'http://localhost:8123' \
  -t 'YOUR_LONG_LIVED_ACCESS_TOKEN' \
  --app-dir .
```

!!! note
    If you are using `uv`, you can use `uv run hassette` instead of `python -m hassette`.

You should see logs showing a successful connection.

![Hassette logs showing successful connection to Home Assistant](../../_static/getting-started-logs.png)

!!! note "Security tip"
    Never commit your access token to version control. In the next section we’ll use configuration files and environment variables to keep secrets out of source control.

### 3. Create your first app

An app is a Python class inheriting from the `App` class.

When creating an App, you can also define a configuration class by inheriting from `AppConfig`. This allows you to specify typed configuration options for your app.

!!! info "More about Apps"
    See the [Writing Apps](../core-concepts/apps/index.md) guide for more details on app structure, lifecycle, and configuration.

Create a file in `apps` named `hello_world.py`:

```bash
touch apps/hello_world.py
```

Add the following:

```python
--8<-- "pages/getting-started/snippets/hello_world.py"
```

The `HelloWorldConfig` class defines configuration fields with defaults. The app inherits from `App` with the config type specified.

In `on_initialize`, we log the greeting and set up an event handler using `self.bus.on_state_change`.

!!! info "Lifecycle Hooks"
    The `on_initialize` method is a lifecycle hook called when the app starts. See the [App Lifecycle](../core-concepts/apps/lifecycle.md) guide for more details.

The `on_motion` handler demonstrates **dependency injection** — instead of receiving the full event object and manually accessing its properties, we use type annotations from `hassette.dependencies` to automatically extract just the data we need. This results in cleaner, more readable code.

!!! info "More about Dependency Injection"
    See the [Dependency Injection](../advanced/dependency-injection.md) guide for more details on how it works and available dependencies.

You don't need additional wiring, by default Hassette will automatically discover your apps.

### 4. Run Hassette

Run Hassette again to see the app in action:

```bash
python -m hassette --base-url 'http://localhost:8123' -t 'YOUR_LONG_LIVED_ACCESS_TOKEN' --app-dir .
```

You should see logs showing the app starting and the greeting being logged.

![Hassette logs showing Hello World message](../../_static/getting-started-app-logs.png)

That is it! Your first Hassette app is running.

## Next steps

Now, let's make things a bit simpler for your next steps by [setting up your configuration](configuration.md).

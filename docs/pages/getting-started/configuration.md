# Configuration

## Using configuration files

So far we’ve taken the long path to show the mechanics. In reality, you’ll want a configuration file.

Configuration files are TOML and define both global Hassette settings and app-specific settings. Hassette looks for `hassette.toml` in:

1. `/config`
2. `./` (current working directory)
3. `./config`

`.env` files are searched in the same locations. Override either path with `--config-file / -c` or `--env-file / -e`.

```bash
python -m hassette -c ./config/hassette.toml -e ./config/.env
```

### Home Assistant token

If you haven't already generated a token, you can follow the steps in the [Creating a Home Assistant token](ha_token.md) guide. Provide the token through one of:

- Environment variables: `HASSETTE__TOKEN`, `HOME_ASSISTANT_TOKEN`, or `HA_TOKEN`.
- CLI arguments: `--token` / `-t`.

!!! warning
    Never store your token directly in `hassette.toml`, as it may be committed to version control. Use environment variables or `.env` files instead.

### `hassette.toml`

Use the config file to set Hassette defaults and register apps:

```toml
--8<-- "pages/getting-started/snippets/hassette.toml"
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

- [Writing Apps](../core-concepts/apps/index.md) – multi-instance apps, typed configs, lifecycle hooks.
- [Event handling patterns](../core-concepts/bus/index.md) – react to state changes, service calls, and custom events.
- [Scheduling tasks](../core-concepts/scheduler/index.md) – run code on intervals, cron schedules, or delays.
- [API usage](../core-concepts/api/index.md) – call services, query states, and interact with Home Assistant.

### ⚙️ Configure your setup

- [Configuration options](../core-concepts/configuration/index.md) – environment variables, secrets, and TOML settings.

### 📚 Learn more

- [vs AppDaemon](../appdaemon-comparison.md) – migration notes if you’re switching from AppDaemon.

### 🔧 Development workflow

- File watching and hot reloading already work out of the box.
- Testing and debugging guides are coming soon.

### Need help?

- [GitHub Issues](https://github.com/NodeJSmith/hassette/issues) for bugs and feature requests.
- [GitHub Discussions](https://github.com/NodeJSmith/hassette/discussions) for questions and community support.

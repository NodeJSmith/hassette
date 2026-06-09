# Quickstart

Install Hassette, write a one-file automation, and see it connect to Home Assistant. For a containerized setup, see [Docker Setup](docker/index.md) instead.

## Prerequisites

- **Python 3.11 or later**: check with `python --version`.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**: this guide uses `uv` to install Hassette.
- **A running Home Assistant instance**: you'll need its URL and a long-lived access token.

## 1. Install Hassette

```bash
uv tool install hassette
```

## 2. Create a Home Assistant token

[Create a long-lived access token](ha_token.md) from the Home Assistant UI (Profile → Security → Long-Lived Access Tokens).

## 3. Set up a project directory

Create an empty directory with a `.env` file and an `apps/` folder:

```bash
mkdir -p my-hassette/apps && cd my-hassette
```

```bash
--8<-- "pages/getting-started/snippets/env_file.sh"
```

Replace the token value with the one you created in step 2. Update `HASSETTE__BASE_URL` to the URL you normally open in your browser, typically `http://homeassistant.local:8123` or `http://<your-ip>:8123`. The double underscores in `HASSETTE__TOKEN` and `HASSETTE__BASE_URL` are required. Hassette uses them to separate configuration namespaces.

## 4. Create your first app

```python
--8<-- "pages/getting-started/snippets/first_app.py"
```

Save this as `apps/main.py`. Hassette scans `apps/` for any class that inherits from `App` and runs all of them.

`MyAppConfig` declares your app's settings as typed class attributes. Hassette loads values from environment variables and `hassette.toml` automatically. `App[MyAppConfig]` ties the config to the app so `self.app_config` is always the right type.

The `async def` and `await` keywords appear throughout Hassette. The rule: write `async def` for all your app methods, and add `await` before any call to `self.bus`, `self.scheduler`, or `self.api`. Regular calls like `self.logger.info()` do not need `await`. That covers everything in this guide.

Every app inherits four objects from Hassette: `self.logger` (Python logger), `self.bus` (event subscriptions), `self.scheduler` (timed jobs), and `self.api` (Home Assistant service calls). Hassette creates them at startup. You just use them.

## 5. Run Hassette

```bash
hassette run -e .env
```

You see output like:

```
--8<-- "pages/getting-started/snippets/run_output.txt"
```

Hassette loaded your config and logged the greeting. Open a second terminal to confirm the connection:

```bash
hassette status
```

```console
╭──────────────────── SystemStatusResponse ────────────────────╮
│  status               ok                                     │
│  websocket_connected  True                                   │
│  uptime_seconds       4.21                                   │
│  app_count            1                                      │
╰──────────────────────────────────────────────────────────────╯
```

```bash
hassette app
```

```console
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃ App Key     ┃ Status  ┃ Display     ┃ Instances ┃ Invoc/1h ┃ Enabled ┃ File       ┃
┃             ┃         ┃ Name        ┃           ┃          ┃         ┃            ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│ my_app      │ running │ MyApp       │ 1         │ 0        │ True    │ main.py    │
└─────────────┴─────────┴─────────────┴───────────┴──────────┴─────────┴────────────┘
```

`websocket_connected: True` confirms the Home Assistant connection. `my_app` shows `running`.

!!! tip "Having trouble?"
    If Hassette fails to connect, check `HASSETTE__BASE_URL` in your `.env` and confirm the token is correct. See [Troubleshooting](../troubleshooting.md) for common issues.

## Next steps

- [Your First Automation](first-automation.md): react to state changes, get typed event data automatically, and schedule recurring jobs
- [Docker Setup](docker/index.md): deploy Hassette in production with Docker Compose

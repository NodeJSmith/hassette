# Quickstart

Install Hassette, write a one-file automation, and see it connect to Home Assistant. For a containerized setup, see [Docker Setup](docker/index.md) instead.

## Prerequisites

- **Python 3.11 or later** — check with `python --version`.
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — this guide uses `uv` to install Hassette.
- **A running Home Assistant instance** — you'll need its URL and a long-lived access token.

## 1. Install Hassette

```bash
uv tool install hassette
```

## 2. Create a Home Assistant token

[Create a long-lived access token](ha_token.md) from the Home Assistant UI.

## 3. Set up a project directory

Create an empty directory with a `.env` file and an `apps/` folder:

```bash
mkdir -p my-hassette/apps && cd my-hassette
```

```bash
--8<-- "pages/getting-started/snippets/env_file.sh"
```

Replace the token value with the one you created in step 2. Update `HASSETTE__BASE_URL` to match your Home Assistant instance.

## 4. Create your first app

```python
--8<-- "pages/getting-started/snippets/first_app.py"
```

Save this as `apps/main.py`. Hassette discovers app classes in `apps/` automatically.

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

- [Your First Automation](first-automation.md) — subscribe to events, use dependency injection, and schedule jobs
- [Docker Setup](docker/index.md) — deploy Hassette in production with Docker Compose

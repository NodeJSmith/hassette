# Local Setup

This is the shortest path to get Hassette running with a config file, a `.env` file for your token, and one tiny app.

!!! tip "Prefer Docker?"
    If you're deploying to a server or want a pre-packaged environment, use the [Docker Deployment](docker/index.md) guide.

## 1. Install Hassette

```bash
--8<-- "pages/getting-started/snippets/install.sh"
```

## 2. Create a project layout

From an empty directory:

```bash
--8<-- "pages/getting-started/snippets/project_layout.sh"
```

## 3. Create a Home Assistant token

Follow the steps in [Creating a Home Assistant token](ha_token.md).

## 4. Create `config/.env`

Create `config/.env`:

```bash
--8<-- "pages/getting-started/snippets/env_file.sh"
```

!!! warning "Security"
    Never commit `.env` files to version control.

## 5. Create `config/hassette.toml`

Create `config/hassette.toml`:

```toml
--8<-- "pages/getting-started/snippets/hassette.toml"
```

Update `base_url` to match your Home Assistant instance.

--8<-- "pages/core-concepts/configuration/snippets/file_discovery.md"

!!! tip
    Run Hassette from your project directory and it will pick up `./config/hassette.toml` and `./config/.env` automatically.

## 6. Create your first app

Create `hassette_apps/main.py`:

```python
--8<-- "pages/getting-started/snippets/first_app.py"
```

!!! note "Typed handlers"
    This example uses a raw event for simplicity. Once you're comfortable, Hassette's [dependency injection](../core-concepts/bus/handlers.md) lets you write cleaner handlers with automatic type conversion:

    ```python
    --8<-- "pages/getting-started/snippets/typed_handler.py:typed-handler"
    ```

## 7. Run Hassette

From your project directory:

```bash
--8<-- "pages/getting-started/snippets/run.sh"
```

Hassette is a long-running process. You should see output like:

```
--8<-- "pages/getting-started/snippets/run_output.txt"
```

The greeting comes from the `greeting` field in your `hassette.toml` — Hassette loaded your config and passed it to your app as `self.app_config.greeting`. When the sun sets, the app calls `self.api.turn_on()` to switch on a light — a complete automation in a few lines of Python.

!!! tip
    If your environment doesn't expose the `hassette` command, run `python -m hassette` instead.

If you need explicit paths:

```bash
--8<-- "pages/getting-started/snippets/run_explicit.sh"
```

!!! tip "Having trouble?"
    If Hassette fails to start or can't connect to Home Assistant, see the [Troubleshooting](../troubleshooting.md) page — the most common issue is an incorrect `base_url` or missing token.

## Next steps

- [Web UI](../web-ui/index.md) — open `http://localhost:8126/ui/` to see the dashboard
- [Creating a Home Assistant token](ha_token.md) — if you haven't set up your token yet
- [Apps Overview](../core-concepts/apps/index.md) — writing your first automation
- [Configuration Overview](../core-concepts/configuration/index.md) — config precedence, file locations, and options
- [Application Configuration](../core-concepts/configuration/applications.md) — registering and configuring apps

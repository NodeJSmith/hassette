# Quickstart

This guide covers **local development**: running Hassette directly with Python and `uv`. If you're deploying to a server or want a containerized setup, use [Docker Deployment](docker/index.md) instead.

## Prerequisites

- **Python 3.11 or later** — Hassette requires Python 3.11+. Check your version with `python --version`.
- **uv** — this guide uses `uv` as the package manager. See the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for installation methods.

## 1. Create a project and install Hassette

`uv init` creates a Python project with a `pyproject.toml`, then `uv add` installs Hassette into it:

```bash
--8<-- "pages/getting-started/snippets/install.sh"
```

## 2. Create a project layout

From your new project directory:

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

!!! note "Double underscore in `HASSETTE__TOKEN`"
    The double underscore (`__`) is required — it follows the Pydantic settings convention for nested configuration. `HASSETTE_TOKEN` (single underscore) will not be recognized and Hassette will start but fail to authenticate with Home Assistant.

!!! warning "Security"
    Never commit `.env` files to version control.

## 5. Create `config/hassette.toml`

Create `config/hassette.toml`:

```toml
--8<-- "pages/getting-started/snippets/hassette.toml"
```

Update `base_url` to match your Home Assistant instance.

!!! note "TOML `[[double bracket]]` syntax"
    The `[[apps.my_app.config]]` section uses TOML array-of-tables syntax, which is required for the `config` section in `hassette.toml`. Using single brackets `[apps.my_app.config]` will cause a configuration parse error.

--8<-- "pages/core-concepts/configuration/snippets/file_discovery.md"

!!! tip
    Run Hassette from your project directory and it will pick up `./config/hassette.toml` and `./config/.env` automatically.

## 6. Create your first app

Create `hassette_apps/main.py`:

```python
--8<-- "pages/getting-started/snippets/first_app.py"
```

!!! warning "Replace `light.porch` with a real entity"
    The example uses `light.porch` — replace it with an entity that actually exists in your Home Assistant instance. You can find your entity IDs in the Home Assistant UI under **Developer Tools > States**.

!!! note "Typed handlers"
    This example uses a raw event for simplicity. Once you're comfortable, Hassette's [dependency injection](../core-concepts/bus/handlers.md) lets you write cleaner handlers with automatic type conversion:

    Add to your imports: `from hassette import D, states`

    ```python
    --8<-- "pages/getting-started/snippets/typed_handler.py:typed-handler"
    ```

## 7. Run Hassette

From your project directory:

```bash
--8<-- "pages/getting-started/snippets/run.sh"
```

`uv run` executes the command inside the project's virtual environment, so the `hassette` CLI is available without manually activating the venv.

Hassette is a long-running process. You should see output like:

```
--8<-- "pages/getting-started/snippets/run_output.txt"
```

Lines 4 and 5 appear only at sunset — you may not see them immediately.

The greeting comes from the `greeting` field in your `hassette.toml` — Hassette loaded your config and passed it to your app as `self.app_config.greeting`. When the sun sets, the app calls `self.api.turn_on()` to switch on a light — a complete automation in a few lines of Python.

If you need explicit paths:

```bash
--8<-- "pages/getting-started/snippets/run_explicit.sh"
```

!!! tip "Having trouble?"
    If Hassette fails to start or can't connect to Home Assistant, see the [Troubleshooting](../troubleshooting.md) page — the most common issue is an incorrect `base_url` or missing token.

## Next steps

- [Your First Automation](first-automation.md) — step-by-step tutorial explaining how the app pattern works
- [Web UI](../web-ui/index.md) — open `http://localhost:8126/ui/` to see the dashboard
- [Apps Overview](../core-concepts/apps/index.md) — writing your first automation
- [Configuration Overview](../core-concepts/configuration/index.md) — config precedence, file locations, and options
- [Application Configuration](../core-concepts/configuration/applications.md) — registering and configuring apps

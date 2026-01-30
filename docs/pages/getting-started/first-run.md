# First Run

This is the shortest path to get Hassette running with a config file, a `.env` file for your token, and one tiny app.

!!! tip "Prefer Docker?"
    If you're deploying to a server or want a pre-packaged environment, use the [Docker Deployment](docker/index.md) guide.

## 1. Install Hassette

```bash
pip install hassette
```

## 2. Create a project layout

From an empty directory:

```bash
mkdir -p config hassette_apps
```

## 3. Create a Home Assistant token

Follow the steps in [Creating a Home Assistant token](ha_token.md).

## 4. Create `config/.env`

Create `config/.env`:

```bash
# config/.env
HASSETTE__TOKEN=your_long_lived_access_token_here
```

!!! warning "Security"
    Never commit `.env` files to version control.

## 5. Create `config/hassette.toml`

Create `config/hassette.toml`:

```toml
--8<-- "pages/getting-started/snippets/hassette.toml"
```

Update `base_url` to match your Home Assistant instance.

!!! note "Where Hassette looks"
    By default, Hassette searches for:

    - `hassette.toml`: `/config/hassette.toml`, `./hassette.toml`, `./config/hassette.toml`
    - `.env`: `/config/.env`, `./.env`, `./config/.env`

    Run Hassette from your project directory and it will pick up `./config/hassette.toml` and `./config/.env` automatically.

## 6. Create your first app

Create `hassette_apps/main.py`:

```python
--8<-- "pages/getting-started/snippets/first_app.py"
```

## 7. Run Hassette

From your project directory:

```bash
hassette
```

!!! tip
    If your environment doesn't expose the `hassette` command, run `python -m hassette` instead.

If you need explicit paths:

```bash
hassette -c ./config/hassette.toml -e ./config/.env
```

## Next steps

- Learn config precedence and options in [Configuration Overview](../core-concepts/configuration/index.md).
- Register and configure more apps in [Application Configuration](../core-concepts/configuration/applications.md).
- Use typed app config models in [App Configuration](../core-concepts/apps/configuration.md).

If you want a higher-level map of the docs (without repeating the tutorial), see [Getting Started Overview](index.md).

If you want details on config discovery, overrides, and file locations, see [Configuration Files](configuration.md).

# Configuration Overview

Hassette configuration controls how the framework connects to Home Assistant, discovers your app files, manages the web UI, and stores persistent data. All settings live in a single `hassette.toml` file (or can be overridden via environment variables or CLI flags).

## Configuration Sources

Hassette loads configuration from multiple sources, applied in this precedence order (highest to lowest):

1. **CLI flags** — arguments passed to `hassette` at startup (e.g., `--base-url`, `--token`)
2. **Environment variables** — variables like `HASSETTE__TOKEN` or `HASSETTE__BASE_URL`
3. **`.env` files** — loaded from `.env` files; same key names as environment variables
4. **`hassette.toml`** — the primary configuration file

When the same setting appears in multiple sources, the higher-precedence source wins. For example, setting `HASSETTE__TOKEN` in the environment overrides `token` in `hassette.toml`.

## File Locations

--8<-- "pages/core-concepts/configuration/snippets/file_discovery.md"

!!! tip "Docker"
    In Docker, mount your configuration volume to `/config`. Hassette checks `/config/hassette.toml` first.

## Configuration Sections

| Section | Purpose | Reference |
|---------|---------|-----------|
| `[hassette]` | Connection, runtime, storage, web UI, and all global settings | [Global Settings](global.md) |
| `[apps.<name>]` | Register and configure individual apps | [Applications](applications.md) |
| `[[apps.<name>.config]]` | Multiple instances of the same app class | [Applications](applications.md) |

## Credentials

Your Home Assistant long-lived access token should never be committed to version control. Store it as an environment variable or in a `.env` file:

```
HASSETTE__TOKEN=your_token_here
```

See [Authentication](auth.md) for all credential options.

## See Also

- [**Authentication**](auth.md) — setting up tokens and secrets
- [**Global Settings**](global.md) — connecting to Home Assistant and all runtime options
- [**Applications**](applications.md) — registering and configuring your apps
- [**Getting Started**](../../getting-started/index.md) — a guided first run

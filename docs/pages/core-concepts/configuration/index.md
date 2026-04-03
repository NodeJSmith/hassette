# Configuration Overview

This section covers how to configure Hassette and your applications.

## Quick Links

- [**Authentication**](auth.md): Setting up tokens and secrets.
- [**Global Settings**](global.md): Connecting to Home Assistant and runtime options.
- [**Applications**](applications.md): Registering and configuring your apps.
- [**Getting Started**](../../getting-started/index.md): A guided first run.

## Configuration Sources

Hassette loads configuration from multiple sources, with the following precedence (highest to lowest):

1. **CLI Flags**: Arguments passed to `hassette` (e.g., `--base-url`, `--token`).
2. **Environment Variables**: Variables like `HASSETTE__TOKEN`.
3. **Env Files (`.env`)**: Loaded from `.env` files (same keys as environment variables).
4. **TOML Configuration**: The `hassette.toml` file.

## File Locations

--8<-- "pages/core-concepts/configuration/snippets/file_discovery.md"

!!! tip "Docker"
    In Docker, typically mount your configuration volume to `/config`.

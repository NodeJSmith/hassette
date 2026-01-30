![Hassette logo](./_static/hassette-logo.svg){.hero}

# Hassette

A simple, modern, async-first Python framework for building Home Assistant automations.

[Get Started (Local)](pages/getting-started/first-run.md){ .md-button .md-button--primary }
[Deploy with Docker](pages/getting-started/docker/index.md){ .md-button }
[AppDaemon Comparison](pages/appdaemon-comparison.md){ .md-button }

## What is Hassette?

Hassette is a framework that helps you write Home Assistant automations in Python. Instead of using the HA user interface or writing YAML, you create "apps" as Python classes that respond to Home Assistant events, call services, and manage state.

If you're familiar with the Python ecosystem, consider it like a marriage between AppDaemon and FastAPI — HA automations built on modern async Python, Pydantic models, and type safety.

## Why Hassette?

- **Write automations as code**: Build “apps” as Python classes that subscribe to events, call services, and manage state.
- **Async-first, but pragmatic**: Use async where it matters; sync apps are supported too.
- **Type-safe configuration**: Pydantic models give validation, defaults, and IDE help.
- **Dependency injection**: Clean handler signatures that focus on the data you need.
- **Great DX**: Clear logs, fast iteration, and hot reloading during development.

## See it in action

This short clip shows live reloading and the overall “tight feedback loop” you get while building automations.

<video controls autoplay muted loop playsinline style="width: 100%; max-width: 1100px; border-radius: 10px;">
    <source src="./_static/live_reloading.webm" type="video/webm">
    <source src="./_static/live_reloading.mp4" type="video/mp4">
    Your browser does not support the video tag.
</video>

!!! tip

    Looking for setup instructions? Start here: [First Run](pages/getting-started/first-run.md)

## What you can build

- Event-driven automations (state changes, events, scheduled jobs)
- Multi-instance apps with separate configs (e.g., “upstairs” and “downstairs”)
- Typed, validated configuration for safer refactors
- Cleaner integrations with Home Assistant services and entities

## Next steps

- Local setup: [First Run](pages/getting-started/first-run.md)
- Production: [Docker Deployment](pages/getting-started/docker/index.md)
- Core patterns: [Apps Overview](pages/core-concepts/apps/index.md)
- Full configuration: [Configuration Overview](pages/core-concepts/configuration/index.md)
- Migration: [AppDaemon Comparison](pages/appdaemon-comparison.md)

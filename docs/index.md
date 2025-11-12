![Hassette logo](./_static/hassette-logo.svg){.hero}

# Hassette

A simple, modern, async-first Python framework for building Home Assistant automations.

## Why Hassette?

Hassette is designed for developers who want to write Home Assistant automations in Python with modern tooling and type safety.

**Key features**

- **Type safe** – full type annotations and IDE support.
- **Async-first** – built for modern Python with async/await throughout.
- **Simple & focused** – just Home Assistant automations, no complexity creep.
- **Developer experience** – clear errors, solid logging, hot reloading.

Built by a fellow HA geek frustrated with the existing Python automation experience. Read more about [why Hassette exists](pages/why-hassette.md).

## Getting Started

Get running with Hassette in just a few steps.

1. **Create your first app**

    ```python
    --8<-- "pages/getting-started/first_app.py"
    ```

2. **Run Hassette**

    ```bash
    uvx hassette -t $HOME_ASSISTANT_TOKEN \
      --base-url 'http://127.0.0.1:8123' \
      --app-dir .
    ```

3. **Watch Hassette auto-detect your app**

    ![Hassette logs showing automation running](./_static/app-logs.png)

## Next Steps

Ready to build something more complex? Explore the rest of the docs:

- Follow the [getting started guide](pages/getting-started/index.md) for a full walkthrough.
- Dive into [core app patterns](pages/core-concepts/apps/index.md).
- Learn more about the [typed API surface](pages/core-concepts/api/index.md).
- See how Hassette stacks up in the [AppDaemon comparison](pages/comparisons/appdaemon.md).

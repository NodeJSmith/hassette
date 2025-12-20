# Why Hassette?

!!! note
    This page covers motivation and goals. If you just want to build something, skip ahead to [Getting Started](getting-started/index.md).

## Background

I'm a Python developer who wanted to write Home Assistant automations in Python—not YAML. AppDaemon was the obvious choice, and I used it for years, but it never quite clicked.

The lack of type annotations meant I was constantly debugging to figure out what callbacks received. Silent failures were common-get a signature slightly wrong and AppDaemon just ignores your method. The wrapped `log` helper swallowed tracebacks and omitted line numbers. When I tried to write tests for my apps, I discovered AppDaemon [didn't have tests itself](https://github.com/AppDaemon/appdaemon/issues/2142) at the time.

After a year of frustration I built a small tool to query states and call services. It grew—scheduling, event listeners, hot reloading—until the framework was larger than my apps. I split it into its own project and kept iterating. Hassette has been running my production automations for months now.

## Principles

- **Type safety first.** Pydantic models, pyright checks, fully typed public APIs. No stepping through code to discover basic types.
- **Async by default.** Modern Python libraries expect it. Sync bridges exist where needed.
- **Tight scope.** Home Assistant automations only-no dashboards, no arbitrary plugins. MQTT may land eventually but won't be a first-class citizen.
- **Ship with tests.** Real coverage on the core, plus a test harness for your own apps (coming soon).
- **Boring logging.** Plain stdlib loggers. Exceptions don't crash the system, but you get full tracebacks with line numbers.

## Roadmap

- Simple web UI for logs
- Public test fixtures
- Home Assistant add-on

## Coming from AppDaemon?

See the [detailed comparison](appdaemon-comparison.md) for differences and migration tips.
